"""Prompt and model lifecycle rules for TK-103-01."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PromptVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ModelVersionStatus(StrEnum):
    REGISTERED = "REGISTERED"
    EVALUATED = "EVALUATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class DeploymentAction(StrEnum):
    CANARY = "CANARY"
    FULL = "FULL"
    ROLLBACK = "ROLLBACK"


class DeploymentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


MODEL_VERSION_TRANSITIONS = {
    ModelVersionStatus.REGISTERED: {ModelVersionStatus.EVALUATED, ModelVersionStatus.ARCHIVED},
    ModelVersionStatus.EVALUATED: {
        ModelVersionStatus.APPROVED,
        ModelVersionStatus.REJECTED,
        ModelVersionStatus.ARCHIVED,
    },
    ModelVersionStatus.APPROVED: {ModelVersionStatus.ARCHIVED},
    ModelVersionStatus.REJECTED: {ModelVersionStatus.ARCHIVED},
    ModelVersionStatus.ARCHIVED: set(),
}


class InvalidLifecycleTransition(ValueError):
    """The requested publication or deployment transition is not allowed."""


class GovernanceResourceNotFound(ValueError):
    """A requested prompt, model or version does not exist."""


@dataclass(frozen=True, slots=True)
class DeploymentRequest:
    model_version_id: UUID
    scene: str
    environment: str
    traffic_percent: int
    deployed_by: UUID
    reason: str
    request_id: str = "internal"

    def validate(self) -> None:
        if not self.scene.strip():
            raise ValueError("scene must not be blank")
        if not self.environment.strip():
            raise ValueError("environment must not be blank")
        if not 1 <= self.traffic_percent <= 100:
            raise ValueError("traffic_percent must be between 1 and 100")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")

    @property
    def action(self) -> DeploymentAction:
        return DeploymentAction.FULL if self.traffic_percent == 100 else DeploymentAction.CANARY


def validate_model_transition(current: str, target: str) -> None:
    try:
        current_status = ModelVersionStatus(current)
        target_status = ModelVersionStatus(target)
    except ValueError as exc:
        raise InvalidLifecycleTransition("unknown model version status") from exc
    if target_status not in MODEL_VERSION_TRANSITIONS[current_status]:
        raise InvalidLifecycleTransition(
            f"model version cannot transition from {current_status} to {target_status}"
        )


def validate_deployable(status: str) -> None:
    if status != ModelVersionStatus.APPROVED:
        raise InvalidLifecycleTransition("only APPROVED model versions can be deployed")


def validate_canary_capacity(active_percent: int, requested_percent: int) -> None:
    if active_percent + requested_percent > 100:
        raise InvalidLifecycleTransition("active canary traffic cannot exceed 100 percent")
