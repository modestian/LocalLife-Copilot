"""Transactional prompt publication and model deployment repository."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.governance import (
    DeploymentAction,
    DeploymentRequest,
    DeploymentStatus,
    GovernanceResourceNotFound,
    InvalidLifecycleTransition,
    PromptVersionStatus,
    validate_canary_capacity,
    validate_deployable,
    validate_model_transition,
)
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.governance import (
    ModelDeployment,
    ModelVersion,
    PromptDefinition,
    PromptVersion,
)


class SQLAlchemyGovernanceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_prompt_version(
        self,
        *,
        prompt_definition_id: UUID,
        content: str,
        variables: dict[str, object],
        created_by: UUID,
    ) -> PromptVersion:
        if not content.strip():
            raise ValueError("prompt content must not be blank")
        content_hash = _prompt_hash(content, variables)
        async with self._session_factory() as session, session.begin():
            definition = await session.scalar(
                select(PromptDefinition)
                .where(PromptDefinition.id == prompt_definition_id)
                .with_for_update()
            )
            if definition is None:
                raise GovernanceResourceNotFound("prompt definition not found")
            latest = await session.scalar(
                select(func.max(PromptVersion.version_no)).where(
                    PromptVersion.prompt_definition_id == prompt_definition_id
                )
            )
            row = PromptVersion(
                prompt_definition_id=prompt_definition_id,
                version_no=(latest or 0) + 1,
                content=content,
                variables_json=dict(variables),
                content_hash=content_hash,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            return row

    async def publish_prompt(self, prompt_version_id: UUID, *, published_by: UUID) -> PromptVersion:
        async with self._session_factory() as session, session.begin():
            target = await session.scalar(
                select(PromptVersion).where(PromptVersion.id == prompt_version_id).with_for_update()
            )
            if target is None:
                raise GovernanceResourceNotFound("prompt version not found")
            if target.status != PromptVersionStatus.DRAFT:
                raise InvalidLifecycleTransition("only DRAFT prompt versions can be published")
            current = (
                await session.scalars(
                    select(PromptVersion)
                    .where(
                        PromptVersion.prompt_definition_id == target.prompt_definition_id,
                        PromptVersion.status == PromptVersionStatus.PUBLISHED,
                    )
                    .with_for_update()
                )
            ).all()
            for row in current:
                row.status = PromptVersionStatus.ARCHIVED
            target.status = PromptVersionStatus.PUBLISHED
            target.published_at = utc_now()
            target.published_by = published_by
            target.publication_action = "PUBLISH"
            target.publication_result = "SUCCEEDED"
            await session.flush()
            return target

    async def rollback_prompt(
        self, prompt_version_id: UUID, *, rolled_back_by: UUID
    ) -> PromptVersion:
        """Publish historical content as a new version without mutating history."""
        async with self._session_factory() as session, session.begin():
            target = await session.scalar(
                select(PromptVersion).where(PromptVersion.id == prompt_version_id).with_for_update()
            )
            if target is None:
                raise GovernanceResourceNotFound("prompt rollback target not found")
            definition = await session.scalar(
                select(PromptDefinition)
                .where(PromptDefinition.id == target.prompt_definition_id)
                .with_for_update()
            )
            if definition is None:
                raise GovernanceResourceNotFound("prompt definition not found")
            latest = await session.scalar(
                select(func.max(PromptVersion.version_no)).where(
                    PromptVersion.prompt_definition_id == target.prompt_definition_id
                )
            )
            current = (
                await session.scalars(
                    select(PromptVersion)
                    .where(
                        PromptVersion.prompt_definition_id == target.prompt_definition_id,
                        PromptVersion.status == PromptVersionStatus.PUBLISHED,
                    )
                    .with_for_update()
                )
            ).all()
            for row in current:
                row.status = PromptVersionStatus.ARCHIVED
            rollback = PromptVersion(
                prompt_definition_id=target.prompt_definition_id,
                version_no=(latest or 0) + 1,
                content=target.content,
                variables_json=dict(target.variables_json),
                status=PromptVersionStatus.PUBLISHED,
                content_hash=target.content_hash,
                created_by=rolled_back_by,
                published_at=utc_now(),
                published_by=rolled_back_by,
                publication_action="ROLLBACK",
                publication_result="SUCCEEDED",
            )
            session.add(rollback)
            await session.flush()
            return rollback

    async def transition_model(self, model_version_id: UUID, target_status: str) -> ModelVersion:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(ModelVersion).where(ModelVersion.id == model_version_id).with_for_update()
            )
            if row is None:
                raise GovernanceResourceNotFound("model version not found")
            validate_model_transition(row.status, target_status)
            row.status = target_status
            await session.flush()
            return row

    async def deploy_model(self, request: DeploymentRequest) -> ModelDeployment:
        request.validate()
        async with self._session_factory() as session, session.begin():
            version = await session.scalar(
                select(ModelVersion)
                .where(ModelVersion.id == request.model_version_id)
                .with_for_update()
            )
            if version is None:
                raise GovernanceResourceNotFound("model version not found")
            validate_deployable(version.status)
            active = await _active_deployments(session, request.scene, request.environment)
            if request.action is DeploymentAction.CANARY:
                validate_canary_capacity(
                    sum(row.traffic_percent for row in active), request.traffic_percent
                )
            else:
                for row in active:
                    row.status = DeploymentStatus.SUPERSEDED
            deployment = ModelDeployment(
                model_version_id=request.model_version_id,
                scene=request.scene.strip(),
                environment=request.environment.strip(),
                traffic_percent=request.traffic_percent,
                action=request.action,
                status=DeploymentStatus.ACTIVE,
                result="SUCCEEDED",
                deployed_by=request.deployed_by,
                reason=request.reason.strip(),
            )
            session.add(deployment)
            await session.flush()
            return deployment

    async def rollback_model(
        self,
        *,
        scene: str,
        environment: str,
        target_model_version_id: UUID,
        deployed_by: UUID,
        reason: str,
    ) -> ModelDeployment:
        if not reason.strip():
            raise ValueError("reason must not be blank")
        async with self._session_factory() as session, session.begin():
            version = await session.scalar(
                select(ModelVersion)
                .where(ModelVersion.id == target_model_version_id)
                .with_for_update()
            )
            if version is None:
                raise GovernanceResourceNotFound("rollback model version not found")
            validate_deployable(version.status)
            prior_release = await session.scalar(
                select(ModelDeployment.id).where(
                    ModelDeployment.scene == scene.strip(),
                    ModelDeployment.environment == environment.strip(),
                    ModelDeployment.model_version_id == target_model_version_id,
                    ModelDeployment.result == "SUCCEEDED",
                )
            )
            if prior_release is None:
                raise InvalidLifecycleTransition("rollback target was never successfully deployed")
            active = await _active_deployments(session, scene.strip(), environment.strip())
            for row in active:
                row.status = DeploymentStatus.SUPERSEDED
            rollback = ModelDeployment(
                model_version_id=target_model_version_id,
                scene=scene.strip(),
                environment=environment.strip(),
                traffic_percent=100,
                action=DeploymentAction.ROLLBACK,
                status=DeploymentStatus.ACTIVE,
                result="SUCCEEDED",
                deployed_by=deployed_by,
                reason=reason.strip(),
            )
            session.add(rollback)
            await session.flush()
            return rollback


async def _active_deployments(
    session: AsyncSession, scene: str, environment: str
) -> list[ModelDeployment]:
    return list(
        (
            await session.scalars(
                select(ModelDeployment)
                .where(
                    ModelDeployment.scene == scene,
                    ModelDeployment.environment == environment,
                    ModelDeployment.status == DeploymentStatus.ACTIVE,
                )
                .with_for_update()
            )
        ).all()
    )


def _prompt_hash(content: str, variables: dict[str, object]) -> str:
    canonical = json.dumps(variables, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{content}\n{canonical}".encode()).hexdigest()
