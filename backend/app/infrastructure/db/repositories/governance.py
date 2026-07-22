"""Transactional prompt publication and model deployment repository."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
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
from app.core.ids import uuid7
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.governance import (
    AuditLog,
    ModelDefinition,
    ModelDeployment,
    ModelDeploymentRoute,
    ModelVersion,
    PromptDefinition,
    PromptVersion,
)


class SQLAlchemyGovernanceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_prompt(
        self,
        *,
        code: str,
        name: str,
        scene: str,
        description: str | None,
        content: str,
        variables: dict[str, object],
        created_by: UUID,
        request_id: str,
    ) -> PromptVersion:
        for field_name, value in (("code", code), ("name", name), ("scene", scene)):
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")
        if not content.strip():
            raise ValueError("prompt content must not be blank")
        async with self._session_factory() as session, session.begin():
            definition = await session.scalar(
                select(PromptDefinition)
                .where(PromptDefinition.code == code.strip())
                .with_for_update()
            )
            if definition is None:
                definition = PromptDefinition(
                    code=code.strip(),
                    name=name.strip(),
                    scene=scene.strip(),
                    description=description.strip() if description else None,
                )
                session.add(definition)
                await session.flush()
            elif definition.scene != scene.strip():
                raise ValueError("prompt code already belongs to another scene")
            row = await _create_prompt_version(
                session,
                definition.id,
                content=content,
                variables=variables,
                created_by=created_by,
            )
            _append_audit(
                session,
                actor_id=created_by,
                action="PROMPT_VERSION_CREATED",
                resource_type="PROMPT",
                resource_id=row.id,
                request_id=request_id,
                result="SUCCEEDED",
                after_summary={
                    "definition_id": str(definition.id),
                    "version_no": row.version_no,
                    "content_hash": row.content_hash,
                },
            )
            return row

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
        async with self._session_factory() as session, session.begin():
            definition = await session.scalar(
                select(PromptDefinition)
                .where(PromptDefinition.id == prompt_definition_id)
                .with_for_update()
            )
            if definition is None:
                raise GovernanceResourceNotFound("prompt definition not found")
            return await _create_prompt_version(
                session,
                prompt_definition_id,
                content=content,
                variables=variables,
                created_by=created_by,
            )

    async def publish_prompt(
        self,
        prompt_version_id: UUID,
        *,
        published_by: UUID,
        request_id: str = "internal",
        reason: str | None = None,
    ) -> PromptVersion:
        async with self._session_factory() as session, session.begin():
            target_definition_id = await session.scalar(
                select(PromptVersion.prompt_definition_id).where(
                    PromptVersion.id == prompt_version_id
                )
            )
            if target_definition_id is None:
                raise GovernanceResourceNotFound("prompt version not found")
            # Every publication for one prompt definition uses the same lock anchor.
            # Locking the definition before any version row prevents two different
            # drafts from being published concurrently and avoids inverted lock order.
            definition = await session.scalar(
                select(PromptDefinition)
                .where(PromptDefinition.id == target_definition_id)
                .with_for_update()
            )
            if definition is None:
                raise GovernanceResourceNotFound("prompt definition not found")
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
            _append_audit(
                session,
                actor_id=published_by,
                action="PROMPT_PUBLISH",
                resource_type="PROMPT",
                resource_id=target.id,
                request_id=request_id,
                result="SUCCEEDED",
                after_summary={
                    "definition_id": str(target.prompt_definition_id),
                    "version_no": target.version_no,
                    "reason": reason,
                },
            )
            await session.flush()
            return target

    async def rollback_prompt(
        self,
        prompt_version_id: UUID,
        *,
        rolled_back_by: UUID,
        request_id: str = "internal",
        reason: str | None = None,
    ) -> PromptVersion:
        """Publish historical content as a new version without mutating history."""
        async with self._session_factory() as session, session.begin():
            target_definition_id = await session.scalar(
                select(PromptVersion.prompt_definition_id).where(
                    PromptVersion.id == prompt_version_id
                )
            )
            if target_definition_id is None:
                raise GovernanceResourceNotFound("prompt rollback target not found")
            definition = await session.scalar(
                select(PromptDefinition)
                .where(PromptDefinition.id == target_definition_id)
                .with_for_update()
            )
            if definition is None:
                raise GovernanceResourceNotFound("prompt definition not found")
            target = await session.scalar(
                select(PromptVersion).where(PromptVersion.id == prompt_version_id).with_for_update()
            )
            if target is None:
                raise GovernanceResourceNotFound("prompt rollback target not found")
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
            _append_audit(
                session,
                actor_id=rolled_back_by,
                action="PROMPT_ROLLBACK",
                resource_type="PROMPT",
                resource_id=rollback.id,
                request_id=request_id,
                result="SUCCEEDED",
                after_summary={
                    "definition_id": str(target.prompt_definition_id),
                    "source_version_id": str(target.id),
                    "version_no": rollback.version_no,
                    "reason": reason,
                },
            )
            await session.flush()
            return rollback

    async def register_model(
        self,
        *,
        code: str,
        name: str,
        task_type: str,
        provider: str,
        version: str,
        base_model_ref: str,
        adapter_uri: str,
        artifact_sha256: str,
        dimension: int | None,
        labels: list[str] | None,
        metrics: dict[str, object] | None,
        created_by: UUID,
        request_id: str,
    ) -> ModelVersion:
        required = {
            "code": code,
            "name": name,
            "task_type": task_type,
            "provider": provider,
            "version": version,
            "base_model_ref": base_model_ref,
            "adapter_uri": adapter_uri,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")
        normalized_sha = artifact_sha256.strip().lower()
        if len(normalized_sha) != 64 or any(
            char not in "0123456789abcdef" for char in normalized_sha
        ):
            raise ValueError("artifact_sha256 must be a 64-character hexadecimal digest")
        async with self._session_factory() as session, session.begin():
            definition = await session.scalar(
                select(ModelDefinition)
                .where(ModelDefinition.code == code.strip())
                .with_for_update()
            )
            if definition is None:
                definition = ModelDefinition(
                    code=code.strip(),
                    name=name.strip(),
                    task_type=task_type.strip(),
                    provider=provider.strip(),
                )
                session.add(definition)
                await session.flush()
            elif (definition.task_type, definition.provider) != (
                task_type.strip(),
                provider.strip(),
            ):
                raise ValueError("model code already belongs to another task type or provider")
            row = ModelVersion(
                model_definition_id=definition.id,
                version=version.strip(),
                base_model_ref=base_model_ref.strip(),
                adapter_uri=adapter_uri.strip(),
                artifact_sha256=normalized_sha,
                dimension=dimension,
                labels_json=list(labels) if labels is not None else None,
                metrics_json=dict(metrics) if metrics is not None else None,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            _append_audit(
                session,
                actor_id=created_by,
                action="MODEL_VERSION_REGISTERED",
                resource_type="MODEL",
                resource_id=row.id,
                request_id=request_id,
                result="SUCCEEDED",
                after_summary={
                    "definition_id": str(definition.id),
                    "version": row.version,
                    "artifact_sha256": row.artifact_sha256,
                },
            )
            return row

    async def list_models(self) -> list[tuple[ModelVersion, ModelDefinition]]:
        async with self._session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(ModelVersion, ModelDefinition)
                        .join(
                            ModelDefinition,
                            ModelDefinition.id == ModelVersion.model_definition_id,
                        )
                        .order_by(ModelDefinition.code, ModelVersion.created_at.desc())
                    )
                ).tuples()
            )

    async def transition_model(
        self,
        model_version_id: UUID,
        target_status: str,
        *,
        actor_id: UUID | None = None,
        request_id: str = "internal",
        reason: str | None = None,
    ) -> ModelVersion:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(ModelVersion).where(ModelVersion.id == model_version_id).with_for_update()
            )
            if row is None:
                raise GovernanceResourceNotFound("model version not found")
            previous_status = row.status
            validate_model_transition(row.status, target_status)
            row.status = target_status
            if actor_id is not None:
                _append_audit(
                    session,
                    actor_id=actor_id,
                    action="MODEL_STATUS_TRANSITION",
                    resource_type="MODEL",
                    resource_id=row.id,
                    request_id=request_id,
                    result="SUCCEEDED",
                    before_summary={"status": previous_status},
                    after_summary={"status": target_status, "reason": reason},
                )
            await session.flush()
            return row

    async def deploy_model(self, request: DeploymentRequest) -> ModelDeployment:
        request.validate()
        async with self._session_factory() as session, session.begin():
            scene = request.scene.strip()
            environment = request.environment.strip()
            await _lock_deployment_route(session, scene, environment)
            version = await session.scalar(
                select(ModelVersion)
                .where(ModelVersion.id == request.model_version_id)
                .with_for_update()
            )
            if version is None:
                raise GovernanceResourceNotFound("model version not found")
            validate_deployable(version.status)
            active = await _active_deployments(session, scene, environment)
            if request.action is DeploymentAction.CANARY:
                validate_canary_capacity(
                    sum(row.traffic_percent for row in active), request.traffic_percent
                )
                new_status = DeploymentStatus.CANARY
            else:
                for row in active:
                    row.status = DeploymentStatus.SUPERSEDED
                new_status = DeploymentStatus.ACTIVE
            deployment = ModelDeployment(
                model_version_id=request.model_version_id,
                scene=scene,
                environment=environment,
                traffic_percent=request.traffic_percent,
                action=request.action,
                status=new_status,
                result="SUCCEEDED",
                deployed_by=request.deployed_by,
                reason=request.reason.strip(),
            )
            session.add(deployment)
            await session.flush()
            _append_audit(
                session,
                actor_id=request.deployed_by,
                action=f"MODEL_{request.action.value}",
                resource_type="MODEL",
                resource_id=request.model_version_id,
                request_id=request.request_id,
                result="SUCCEEDED",
                after_summary={
                    "deployment_id": str(deployment.id),
                    "scene": scene,
                    "environment": environment,
                    "traffic_percent": request.traffic_percent,
                    "reason": request.reason.strip(),
                },
            )
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
        request_id: str = "internal",
    ) -> ModelDeployment:
        if not reason.strip():
            raise ValueError("reason must not be blank")
        async with self._session_factory() as session, session.begin():
            normalized_scene = scene.strip()
            normalized_environment = environment.strip()
            await _lock_deployment_route(session, normalized_scene, normalized_environment)
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
                    ModelDeployment.scene == normalized_scene,
                    ModelDeployment.environment == normalized_environment,
                    ModelDeployment.model_version_id == target_model_version_id,
                    ModelDeployment.result == "SUCCEEDED",
                )
            )
            if prior_release is None:
                raise InvalidLifecycleTransition("rollback target was never successfully deployed")
            active = await _active_deployments(session, normalized_scene, normalized_environment)
            for row in active:
                row.status = DeploymentStatus.ROLLED_BACK
            rollback = ModelDeployment(
                model_version_id=target_model_version_id,
                scene=normalized_scene,
                environment=normalized_environment,
                traffic_percent=100,
                action=DeploymentAction.ROLLBACK,
                status=DeploymentStatus.ACTIVE,
                result="SUCCEEDED",
                deployed_by=deployed_by,
                reason=reason.strip(),
            )
            session.add(rollback)
            await session.flush()
            _append_audit(
                session,
                actor_id=deployed_by,
                action="MODEL_ROLLBACK",
                resource_type="MODEL",
                resource_id=target_model_version_id,
                request_id=request_id,
                result="SUCCEEDED",
                after_summary={
                    "deployment_id": str(rollback.id),
                    "scene": normalized_scene,
                    "environment": normalized_environment,
                    "traffic_percent": 100,
                    "reason": reason.strip(),
                },
            )
            await session.flush()
            return rollback

    async def append_operation_audit(
        self,
        *,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        request_id: str,
        result: str,
        summary: dict[str, object] | None = None,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            _append_audit(
                session,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                result=result,
                after_summary=summary,
            )


async def _active_deployments(
    session: AsyncSession, scene: str, environment: str
) -> list[ModelDeployment]:
    """Return all ACTIVE and CANARY deployments for a route (locked for update)."""
    return list(
        (
            await session.scalars(
                select(ModelDeployment)
                .where(
                    ModelDeployment.scene == scene,
                    ModelDeployment.environment == environment,
                    ModelDeployment.status.in_([DeploymentStatus.ACTIVE, DeploymentStatus.CANARY]),
                )
                .with_for_update()
            )
        ).all()
    )


async def _create_prompt_version(
    session: AsyncSession,
    prompt_definition_id: UUID,
    *,
    content: str,
    variables: dict[str, object],
    created_by: UUID,
) -> PromptVersion:
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
        content_hash=_prompt_hash(content, variables),
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row


async def _lock_deployment_route(session: AsyncSession, scene: str, environment: str) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "mysql":
        statement = mysql_insert(ModelDeploymentRoute).values(
            id=uuid7(), scene=scene, environment=environment
        )
        await session.execute(statement.on_duplicate_key_update(scene=statement.inserted.scene))
    else:
        existing = await session.scalar(
            select(ModelDeploymentRoute).where(
                ModelDeploymentRoute.scene == scene,
                ModelDeploymentRoute.environment == environment,
            )
        )
        if existing is None:
            session.add(ModelDeploymentRoute(scene=scene, environment=environment))
            await session.flush()
    route = await session.scalar(
        select(ModelDeploymentRoute)
        .where(
            ModelDeploymentRoute.scene == scene,
            ModelDeploymentRoute.environment == environment,
        )
        .with_for_update()
    )
    if route is None:
        raise RuntimeError("model deployment route lock could not be acquired")


def _append_audit(
    session: AsyncSession,
    *,
    actor_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    request_id: str,
    result: str,
    before_summary: dict[str, object] | None = None,
    after_summary: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action[:64],
            resource_type=resource_type[:64],
            resource_id=resource_id,
            request_id=request_id[:128] or "internal",
            result=result,
            before_summary_json=before_summary,
            after_summary_json=after_summary,
        )
    )


def _prompt_hash(content: str, variables: dict[str, object]) -> str:
    canonical = json.dumps(variables, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{content}\n{canonical}".encode()).hexdigest()
