"""Unit tests for user-submitted review endpoints."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies.authorization import get_authorization_service
from app.application.authorization import (
    AuthorizationPrincipal,
    AuthorizationService,
    PermissionRule,
    ResourceGrantRule,
    ResourceType,
    RoleInfo,
)
from app.application.content_safety import ContentCheckResult, ContentDirection
from app.core.config import Settings
from app.core.ids import uuid7
from app.core.security import AccessTokenService
from app.main import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _access_tokens() -> AccessTokenService:
    return AccessTokenService(
        secret_key="review-test-secret-at-least-32-bytes-long",
        issuer="review-test",
        audience="review-api",
        ttl=timedelta(minutes=30),
    )


def _user_principal(merchant_id: UUID) -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="reviewer",
        display_name="测试用户",
        email="reviewer@example.com",
        department_id=None,
        roles=(RoleInfo("USER", "普通用户"),),
        permissions=(PermissionRule("merchant.read", "MERCHANT", "READ"),),
        resource_grants=(ResourceGrantRule(ResourceType.MERCHANT, merchant_id, "READ"),),
    )


def _admin_principal() -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="admin",
        display_name="管理员",
        email="admin@example.com",
        department_id=None,
        roles=(RoleInfo("PLATFORM_ADMIN", "平台管理员"),),
        permissions=(),
        resource_grants=(),
    )


@dataclass
class FakeReview:
    id: UUID
    merchant_id: UUID
    user_id: UUID | None
    content: str
    rating: Decimal | None
    status: str
    created_at: object

    def __post_init__(self) -> None:
        from datetime import UTC, datetime

        if not isinstance(self.created_at, datetime):
            self.created_at = datetime.now(UTC)


def _build_app(principals: list[AuthorizationPrincipal]) -> tuple:
    access_tokens = _access_tokens()
    repo = AsyncMock()

    class InMemoryAuthRepo:
        def __init__(self, plist: list[AuthorizationPrincipal]) -> None:
            self._map = {p.user_id: p for p in plist}

        async def load_principal(self, user_id: UUID) -> AuthorizationPrincipal | None:
            return self._map.get(user_id)

    service = AuthorizationService(InMemoryAuthRepo(principals), access_tokens)
    app = create_app(readiness_checks={}, settings=Settings())
    app.dependency_overrides[get_authorization_service] = lambda: service
    app.state.operations_repository = repo
    return app, access_tokens, repo


# ---------------------------------------------------------------------------
# Tests: POST /merchants/{merchant_id}/reviews
# ---------------------------------------------------------------------------


class TestSubmitUserReview:
    def test_submit_review_success(self) -> None:
        merchant_id = uuid7()
        principal = _user_principal(merchant_id)
        app, tokens, repo = _build_app([principal])

        fake_review = FakeReview(
            id=uuid7(),
            merchant_id=merchant_id,
            user_id=principal.user_id,
            content="这家店环境很好",
            rating=Decimal("4.5"),
            status="PENDING",
            created_at=None,
        )
        repo.create_user_review.return_value = fake_review
        token = tokens.issue(principal.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/merchants/{merchant_id}/reviews",
                json={"content": "这家店环境很好", "rating": 4.5},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["status"] == "PENDING"
        assert data["merchant_id"] == str(merchant_id)
        repo.create_user_review.assert_awaited_once()

    def test_submit_review_merchant_not_found(self) -> None:
        merchant_id = uuid7()
        principal = _user_principal(merchant_id)
        app, tokens, repo = _build_app([principal])
        repo.create_user_review.side_effect = LookupError("merchant not found")
        token = tokens.issue(principal.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/merchants/{merchant_id}/reviews",
                json={"content": "评论", "rating": 3.0},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 404

    def test_submit_review_sensitive_content_rejected(self) -> None:
        merchant_id = uuid7()
        principal = _user_principal(merchant_id)
        app, tokens, repo = _build_app([principal])

        # Attach a content safety service that blocks
        safety = AsyncMock()
        safety.check.return_value = ContentCheckResult(
            allowed=False,
            direction=ContentDirection.INPUT,
            matched_rule_ids=(uuid7(),),
            decision="BLOCK_INPUT",
        )
        app.state.content_safety_service = safety
        token = tokens.issue(principal.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/merchants/{merchant_id}/reviews",
                json={"content": "违禁内容", "rating": 1.0},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 422
        assert "SENSITIVE_CONTENT_REJECTED" in response.json()["code"]

    def test_submit_review_requires_auth(self) -> None:
        merchant_id = uuid7()
        principal = _user_principal(merchant_id)
        app, _, _ = _build_app([principal])

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/merchants/{merchant_id}/reviews",
                json={"content": "评论", "rating": 3.0},
            )

        assert response.status_code == 401

    def test_submit_review_validation_error(self) -> None:
        merchant_id = uuid7()
        principal = _user_principal(merchant_id)
        app, tokens, _ = _build_app([principal])
        token = tokens.issue(principal.user_id).value

        with TestClient(app) as client:
            # rating > 5
            response = client.post(
                f"/api/v1/merchants/{merchant_id}/reviews",
                json={"content": "评论", "rating": 6.0},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: GET /users/me/reviews
# ---------------------------------------------------------------------------


class TestListMyReviews:
    def test_list_my_reviews(self) -> None:
        merchant_id = uuid7()
        principal = _user_principal(merchant_id)
        app, tokens, repo = _build_app([principal])

        fake_reviews = [
            FakeReview(
                id=uuid7(),
                merchant_id=merchant_id,
                user_id=principal.user_id,
                content="好评",
                rating=Decimal("5"),
                status="PUBLISHED",
                created_at=None,
            ),
            FakeReview(
                id=uuid7(),
                merchant_id=merchant_id,
                user_id=principal.user_id,
                content="待审",
                rating=Decimal("3"),
                status="PENDING",
                created_at=None,
            ),
        ]
        repo.list_user_reviews.return_value = (fake_reviews, 2)
        token = tokens.issue(principal.user_id).value

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/users/me/reviews",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["status"] == "PUBLISHED"
        assert data["items"][1]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Tests: POST /reviews/{review_id}/moderate
# ---------------------------------------------------------------------------


class TestModerateReview:
    def test_approve_review(self) -> None:
        merchant_id = uuid7()
        admin = _admin_principal()
        app, tokens, repo = _build_app([admin])

        review_id = uuid7()
        fake_review = FakeReview(
            id=review_id,
            merchant_id=merchant_id,
            user_id=uuid7(),
            content="好评",
            rating=Decimal("5"),
            status="PUBLISHED",
            created_at=None,
        )
        repo.moderate_user_review.return_value = fake_review
        token = tokens.issue(admin.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/reviews/{review_id}/moderate",
                json={"decision": "APPROVE", "reason": "内容合规"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "PUBLISHED"

    def test_reject_review(self) -> None:
        merchant_id = uuid7()
        admin = _admin_principal()
        app, tokens, repo = _build_app([admin])

        review_id = uuid7()
        fake_review = FakeReview(
            id=review_id,
            merchant_id=merchant_id,
            user_id=uuid7(),
            content="违规",
            rating=Decimal("1"),
            status="REJECTED",
            created_at=None,
        )
        repo.moderate_user_review.return_value = fake_review
        token = tokens.issue(admin.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/reviews/{review_id}/moderate",
                json={"decision": "REJECT", "reason": "内容不当"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "REJECTED"

    def test_moderate_requires_admin(self) -> None:
        merchant_id = uuid7()
        user = _user_principal(merchant_id)
        app, tokens, _ = _build_app([user])
        token = tokens.issue(user.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/reviews/{uuid7()}/moderate",
                json={"decision": "APPROVE", "reason": "ok"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 403

    def test_moderate_not_found(self) -> None:
        admin = _admin_principal()
        app, tokens, repo = _build_app([admin])
        repo.moderate_user_review.side_effect = LookupError("review not found")
        token = tokens.issue(admin.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/reviews/{uuid7()}/moderate",
                json={"decision": "APPROVE", "reason": "ok"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 404

    def test_moderate_invalid_status_transition(self) -> None:
        admin = _admin_principal()
        app, tokens, repo = _build_app([admin])
        repo.moderate_user_review.side_effect = ValueError(
            "review is not pending, current status: PUBLISHED"
        )
        token = tokens.issue(admin.user_id).value

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/reviews/{uuid7()}/moderate",
                json={"decision": "APPROVE", "reason": "ok"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 422
