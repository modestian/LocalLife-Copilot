"""End-to-end API contract tests for the completed ST-103 governance surface."""

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.authorization import get_current_principal
from app.api.governance import get_governance_repository, router
from app.application.authorization import AuthorizationPrincipal, RoleInfo
from app.application.governance import InvalidLifecycleTransition
from app.core.api import install_api_contract
from app.core.config import Settings
from app.core.ids import uuid7
from app.main import create_app


def _principal(*, admin: bool = True) -> AuthorizationPrincipal:
    roles = (RoleInfo("PLATFORM_ADMIN", "Platform admin"),) if admin else ()
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="governance-user",
        display_name="Governance user",
        email=None,
        department_id=None,
        roles=roles,
        permissions=(),
        resource_grants=(),
    )


class GovernanceStub:
    def __init__(self) -> None:
        self.definition_id = uuid7()
        self.prompt_id = uuid7()
        self.model_id = uuid7()
        self.audits: list[dict[str, object]] = []
        self.last_deployment_request = None
        self.fail_publish = False

    def _prompt(self, **changes: object) -> SimpleNamespace:
        values = {
            "id": self.prompt_id,
            "prompt_definition_id": self.definition_id,
            "version_no": 1,
            "content": "Recommend {city}",
            "variables_json": {"city": "string"},
            "content_hash": "a" * 64,
            "status": "DRAFT",
            "created_by": uuid7(),
            "created_at": datetime(2026, 7, 21, 12, 0),
            "published_by": None,
            "published_at": None,
            "publication_action": None,
            "publication_result": None,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def _model(self, **changes: object) -> SimpleNamespace:
        values = {
            "id": self.model_id,
            "model_definition_id": self.definition_id,
            "version": "v1",
            "base_model_ref": "base@sha",
            "adapter_uri": "s3://models/v1",
            "artifact_sha256": "b" * 64,
            "dimension": None,
            "labels_json": None,
            "metrics_json": None,
            "status": "REGISTERED",
            "created_by": uuid7(),
            "created_at": datetime(2026, 7, 21, 12, 0),
        }
        values.update(changes)
        return SimpleNamespace(**values)

    async def create_prompt(self, **values: object) -> SimpleNamespace:
        return self._prompt(created_by=values["created_by"])

    async def publish_prompt(self, *args: object, **values: object) -> SimpleNamespace:
        del args
        if self.fail_publish:
            raise InvalidLifecycleTransition("only DRAFT prompt versions can be published")
        return self._prompt(
            status="PUBLISHED",
            published_by=values["published_by"],
            published_at=datetime(2026, 7, 21, 12, 1),
            publication_action="PUBLISH",
            publication_result="SUCCEEDED",
        )

    async def rollback_prompt(self, *args: object, **values: object) -> SimpleNamespace:
        del args
        return self._prompt(
            id=uuid7(),
            version_no=2,
            status="PUBLISHED",
            published_by=values["rolled_back_by"],
            published_at=datetime(2026, 7, 21, 12, 2),
            publication_action="ROLLBACK",
            publication_result="SUCCEEDED",
        )

    async def register_model(self, **values: object) -> SimpleNamespace:
        return self._model(created_by=values["created_by"])

    async def list_models(self) -> list[tuple[SimpleNamespace, SimpleNamespace]]:
        definition = SimpleNamespace(
            code="review-model", name="Review model", task_type="sentiment", provider="local"
        )
        return [(self._model(), definition)]

    async def transition_model(self, *args: object, **values: object) -> SimpleNamespace:
        return self._model(status=str(args[1]))

    async def deploy_model(self, deployment_request) -> SimpleNamespace:
        self.last_deployment_request = deployment_request
        return SimpleNamespace(
            id=uuid7(),
            model_version_id=self.model_id,
            scene=deployment_request.scene,
            environment=deployment_request.environment,
            traffic_percent=deployment_request.traffic_percent,
            action=deployment_request.action,
            status="ACTIVE",
            result="SUCCEEDED",
            deployed_by=deployment_request.deployed_by,
            reason=deployment_request.reason,
            created_at=datetime(2026, 7, 21, 12, 3),
        )

    async def rollback_model(self, **values: object) -> SimpleNamespace:
        return SimpleNamespace(
            id=uuid7(),
            model_version_id=values["target_model_version_id"],
            scene=values["scene"],
            environment=values["environment"],
            traffic_percent=100,
            action="ROLLBACK",
            status="ACTIVE",
            result="SUCCEEDED",
            deployed_by=values["deployed_by"],
            reason=values["reason"],
            created_at=datetime(2026, 7, 21, 12, 4),
        )

    async def append_operation_audit(self, **values: object) -> None:
        self.audits.append(values)


def _client(repository: GovernanceStub, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    settings = Settings()
    install_api_contract(app, settings)
    app.include_router(router, prefix=settings.api_v1_prefix)
    app.dependency_overrides[get_governance_repository] = lambda: repository
    app.dependency_overrides[get_current_principal] = lambda: _principal(admin=admin)
    return TestClient(app)


def test_production_application_exposes_documented_governance_routes() -> None:
    app = create_app(readiness_checks={})
    route_methods = {
        (route.path, method) for route in app.routes for method in getattr(route, "methods", set())
    }
    assert {
        ("/api/v1/prompts", "POST"),
        ("/api/v1/prompts/{prompt_version_id}/publish", "POST"),
        ("/api/v1/prompts/{prompt_version_id}/rollback", "POST"),
        ("/api/v1/models", "GET"),
        ("/api/v1/models", "POST"),
        ("/api/v1/models/{model_version_id}/deploy", "POST"),
        ("/api/v1/models/{model_version_id}/rollback", "POST"),
        ("/api/v1/chat-logs", "GET"),
    } <= route_methods


def test_admin_can_create_publish_and_rollback_prompt_versions() -> None:
    repository = GovernanceStub()
    with _client(repository) as client:
        created = client.post(
            "/api/v1/prompts",
            json={
                "code": "recommendation",
                "name": "Recommendation",
                "scene": "chat",
                "content": "Recommend {city}",
                "variables": {"city": "string"},
            },
        )
        published = client.post(
            f"/api/v1/prompts/{repository.prompt_id}/publish", json={"reason": "approved"}
        )
        rolled_back = client.post(
            f"/api/v1/prompts/{repository.prompt_id}/rollback", json={"reason": "regression"}
        )

    assert created.status_code == 201
    assert created.json()["data"]["content_hash"] == "a" * 64
    assert published.json()["data"]["publication_action"] == "PUBLISH"
    assert rolled_back.json()["data"]["version_no"] == 2


def test_admin_can_register_transition_list_and_deploy_model() -> None:
    repository = GovernanceStub()
    payload = {
        "code": "review-model",
        "name": "Review model",
        "task_type": "sentiment",
        "provider": "local",
        "version": "v1",
        "base_model_ref": "base@sha",
        "adapter_uri": "s3://models/v1",
        "artifact_sha256": "b" * 64,
    }
    with _client(repository) as client:
        registered = client.post("/api/v1/models", json=payload)
        transitioned = client.post(
            f"/api/v1/models/{repository.model_id}/status",
            json={"status": "EVALUATED", "reason": "evaluation complete"},
        )
        listed = client.get("/api/v1/models")
        deployed = client.post(
            f"/api/v1/models/{repository.model_id}/deploy",
            json={
                "scene": "chat",
                "environment": "production",
                "traffic_percent": 10,
                "reason": "canary",
            },
            headers={"X-Request-ID": "deploy-request"},
        )

    assert registered.status_code == 201
    assert transitioned.json()["data"]["status"] == "EVALUATED"
    assert listed.json()["data"]["items"][0]["code"] == "review-model"
    assert deployed.json()["data"]["action"] == "CANARY"
    assert repository.last_deployment_request.request_id == "deploy-request"


def test_failed_release_is_returned_as_conflict_and_audited() -> None:
    repository = GovernanceStub()
    repository.fail_publish = True
    with _client(repository) as client:
        response = client.post(
            f"/api/v1/prompts/{repository.prompt_id}/publish", json={"reason": "retry"}
        )

    assert response.status_code == 409
    assert response.json()["code"] == "GOVERNANCE_CONFLICT"
    assert repository.audits[0]["action"] == "PROMPT_PUBLISH"
    assert repository.audits[0]["result"] == "FAILED"


def test_non_admin_cannot_use_governance_api() -> None:
    with _client(GovernanceStub(), admin=False) as client:
        response = client.get("/api/v1/models")

    assert response.status_code == 403
