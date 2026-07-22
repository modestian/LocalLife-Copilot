"""Create the deterministic local data set used by the ST-702 demonstration.

The command is intentionally idempotent: it uses fixed identifiers and only
inserts missing records, so it can safely be rerun after the business tables
have been cleared.  The password is deliberately supplied at runtime rather
than stored in the repository.
"""

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.cli.create_test_user import ROLE_NAMES
from app.core.config import get_settings
from app.core.security import PasswordService
from app.infrastructure.db.models.conversations import Conversation, Message, MessageSource
from app.infrastructure.db.models.feedback import Feedback, FeedbackAudit
from app.infrastructure.db.models.governance import (
    ModelDefinition,
    ModelDeployment,
    ModelVersion,
)
from app.infrastructure.db.models.identity import (
    Department,
    Permission,
    ResourceGrant,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase
from app.infrastructure.db.models.sentiment import ReviewAnalysis

DEMO_TIME: Final = datetime(2026, 7, 1, 9, 0, 0)
DEMO_TENANT_ID: Final = UUID("70200000-0000-4000-8000-000000000001")
KNOWLEDGE_BASE_ID: Final = UUID("70200000-0000-4000-8000-000000000010")
MERCHANT_QINGHE_ID: Final = UUID("70200000-0000-4000-8000-000000000020")
MERCHANT_SHUXIANG_ID: Final = UUID("70200000-0000-4000-8000-000000000021")
MODEL_DEFINITION_ID: Final = UUID("70200000-0000-4000-8000-000000000030")
MODEL_VERSION_V1_ID: Final = UUID("70200000-0000-4000-8000-000000000031")
MODEL_VERSION_V2_ID: Final = UUID("70200000-0000-4000-8000-000000000032")
DOCUMENT_QINGHE_ID: Final = UUID("70200000-0000-4000-8000-000000000040")
DOCUMENT_SHUXIANG_ID: Final = UUID("70200000-0000-4000-8000-000000000041")
DOCUMENT_QINGHE_VERSION_ID: Final = UUID("70200000-0000-4000-8000-000000000042")
DOCUMENT_SHUXIANG_VERSION_ID: Final = UUID("70200000-0000-4000-8000-000000000043")
CHUNK_QINGHE_ID: Final = UUID("70200000-0000-4000-8000-000000000044")
CHUNK_SHUXIANG_ID: Final = UUID("70200000-0000-4000-8000-000000000045")
CONVERSATION_ID: Final = UUID("70200000-0000-4000-8000-000000000050")
USER_MESSAGE_ID: Final = UUID("70200000-0000-4000-8000-000000000051")
ASSISTANT_MESSAGE_ID: Final = UUID("70200000-0000-4000-8000-000000000052")
FEEDBACK_ID: Final = UUID("70200000-0000-4000-8000-000000000053")
FEEDBACK_AUDIT_ID: Final = UUID("70200000-0000-4000-8000-000000000054")


@dataclass(frozen=True, slots=True)
class DemoUser:
    key: str
    username: str
    display_name: str
    role_code: str


DEMO_USERS: Final = (
    DemoUser("admin", "demo-admin", "演示平台主管理员", "PLATFORM_ADMIN"),
    DemoUser("user", "demo-user", "演示探店用户", "USER"),
    DemoUser("merchant", "demo-merchant", "演示商家运营", "MERCHANT_ADMIN"),
)

DEMO_QUESTIONS: Final = (
    {
        "id": "q-001",
        "question": "清河面馆适合两个人午餐吗？",
        "expected_document_id": str(DOCUMENT_QINGHE_ID),
        "expected_terms": ["双人", "午餐", "排队"],
    },
    {
        "id": "q-002",
        "question": "书香咖啡馆周末是否适合安静办公？",
        "expected_document_id": str(DOCUMENT_SHUXIANG_ID),
        "expected_terms": ["插座", "安静", "周末"],
    },
    {
        "id": "q-003",
        "question": "附近有提供火星料理的店吗？",
        "expected_document_id": None,
        "expected_terms": [],
        "expected_fallback": True,
    },
)

QUESTION_SET_PATH: Final = Path(__file__).resolve().parents[2] / "demo_data" / "questions.json"


@dataclass(frozen=True, slots=True)
class DemoSeedSummary:
    users: int
    merchants: int
    reviews: int
    documents: int
    questions: int


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _review_rows() -> tuple[dict[str, object], ...]:
    """Return a stable, trend-friendly review fixture for the two demo merchants."""

    return (
        {
            "id": "70200000-0000-4000-8000-000000000101",
            "merchant_id": str(MERCHANT_QINGHE_ID),
            "review_text": "牛肉面汤头浓郁，午餐两个人拼小菜刚好。",
            "sentiment": "POSITIVE",
            "confidence": 0.98,
            "aspects": ["口味", "性价比"],
            "reasons": [],
            "date": datetime(2026, 6, 1, 12, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000102",
            "merchant_id": str(MERCHANT_QINGHE_ID),
            "review_text": "面很香，但中午排队超过二十分钟。",
            "sentiment": "NEGATIVE",
            "confidence": 0.95,
            "aspects": ["口味", "排队"],
            "reasons": ["排队时间长"],
            "date": datetime(2026, 6, 4, 12, 30, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000103",
            "merchant_id": str(MERCHANT_QINGHE_ID),
            "review_text": "服务主动，双人套餐分量足。",
            "sentiment": "POSITIVE",
            "confidence": 0.96,
            "aspects": ["服务", "分量"],
            "reasons": [],
            "date": datetime(2026, 6, 8, 12, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000104",
            "merchant_id": str(MERCHANT_QINGHE_ID),
            "review_text": "出餐速度一般，面条口感稳定。",
            "sentiment": "NEUTRAL",
            "confidence": 0.88,
            "aspects": ["出餐速度", "口味"],
            "reasons": [],
            "date": datetime(2026, 6, 12, 12, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000105",
            "merchant_id": str(MERCHANT_QINGHE_ID),
            "review_text": "高峰期座位紧张，建议错峰。",
            "sentiment": "NEGATIVE",
            "confidence": 0.93,
            "aspects": ["座位", "排队"],
            "reasons": ["座位紧张", "排队时间长"],
            "date": datetime(2026, 6, 16, 12, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000106",
            "merchant_id": str(MERCHANT_QINGHE_ID),
            "review_text": "新上的酸梅汤很解腻，整体值得再来。",
            "sentiment": "POSITIVE",
            "confidence": 0.97,
            "aspects": ["饮品", "复购意愿"],
            "reasons": [],
            "date": datetime(2026, 6, 22, 12, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000107",
            "merchant_id": str(MERCHANT_SHUXIANG_ID),
            "review_text": "靠窗座位安静，插座充足，适合办公。",
            "sentiment": "POSITIVE",
            "confidence": 0.99,
            "aspects": ["环境", "设施"],
            "reasons": [],
            "date": datetime(2026, 6, 2, 10, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000108",
            "merchant_id": str(MERCHANT_SHUXIANG_ID),
            "review_text": "周末人多，咖啡出品不错但等候偏久。",
            "sentiment": "NEGATIVE",
            "confidence": 0.92,
            "aspects": ["咖啡", "出餐速度"],
            "reasons": ["等待时间长"],
            "date": datetime(2026, 6, 7, 14, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000109",
            "merchant_id": str(MERCHANT_SHUXIANG_ID),
            "review_text": "背景音乐轻，不会打扰开会。",
            "sentiment": "POSITIVE",
            "confidence": 0.94,
            "aspects": ["环境", "音乐"],
            "reasons": [],
            "date": datetime(2026, 6, 11, 15, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000110",
            "merchant_id": str(MERCHANT_SHUXIANG_ID),
            "review_text": "甜点一般，座位舒适。",
            "sentiment": "NEUTRAL",
            "confidence": 0.84,
            "aspects": ["甜点", "环境"],
            "reasons": [],
            "date": datetime(2026, 6, 17, 14, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000111",
            "merchant_id": str(MERCHANT_SHUXIANG_ID),
            "review_text": "店员会提醒低电量座位，体验贴心。",
            "sentiment": "POSITIVE",
            "confidence": 0.96,
            "aspects": ["服务", "设施"],
            "reasons": [],
            "date": datetime(2026, 6, 21, 11, 0, 0),
        },
        {
            "id": "70200000-0000-4000-8000-000000000112",
            "merchant_id": str(MERCHANT_SHUXIANG_ID),
            "review_text": "下午高峰网络偶有波动。",
            "sentiment": "NEGATIVE",
            "confidence": 0.91,
            "aspects": ["网络", "环境"],
            "reasons": ["网络不稳定"],
            "date": datetime(2026, 6, 25, 15, 0, 0),
        },
    )


async def _add_if_missing(session: AsyncSession, record: object) -> bool:
    record_id = getattr(record, "id", None)
    if record_id is None:
        raise ValueError(f"{type(record).__name__} must expose an id")
    if await session.get(type(record), record_id) is not None:
        return False
    session.add(record)
    return True


async def _seed_roles_and_permissions(
    session: AsyncSession, users: dict[str, User]
) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for offset, role_code in enumerate(("PLATFORM_ADMIN", "USER", "MERCHANT_ADMIN"), start=1):
        role = await session.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            role = Role(
                id=UUID(f"70200000-0000-4000-8000-0000000000{60 + offset}"),
                code=role_code,
                name=ROLE_NAMES[role_code],
                is_system=True,
                status="ACTIVE",
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
            )
            session.add(role)
        else:
            role.status = "ACTIVE"
        roles[role_code] = role

    permissions: dict[str, Permission] = {}
    for offset, (code, resource_type) in enumerate(
        (("demo.knowledge-base.read", "KNOWLEDGE_BASE"), ("demo.merchant.read", "MERCHANT")),
        start=1,
    ):
        permission = await session.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(
                id=UUID(f"70200000-0000-4000-8000-0000000000{70 + offset}"),
                code=code,
                resource_type=resource_type,
                action="READ",
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
            )
            session.add(permission)
        permissions[resource_type] = permission

    await session.flush()
    for user_spec in DEMO_USERS:
        role = roles[user_spec.role_code]
        user = users[user_spec.key]
        if await session.get(UserRole, (user.id, role.id)) is None:
            session.add(UserRole(user_id=user.id, role_id=role.id, granted_at=DEMO_TIME))
    for role_code in ("USER", "MERCHANT_ADMIN"):
        for permission in permissions.values():
            if await session.get(RolePermission, (roles[role_code].id, permission.id)) is None:
                session.add(
                    RolePermission(role_id=roles[role_code].id, permission_id=permission.id)
                )
    return roles


async def _seed_users(session: AsyncSession, password: str) -> dict[str, User]:
    password_hash = PasswordService().hash(password)
    users: dict[str, User] = {}
    for offset, spec in enumerate(DEMO_USERS, start=1):
        user = await session.scalar(
            select(User).where(User.normalized_username == spec.username.casefold())
        )
        if user is None:
            user = User(
                id=UUID(f"70200000-0000-4000-8000-0000000000{50 + offset}"),
                username=spec.username,
                normalized_username=spec.username.casefold(),
                email=f"{spec.username}@demo.local",
                normalized_email=f"{spec.username}@demo.local",
                password_hash=password_hash,
                display_name=spec.display_name,
                department_id=DEMO_TENANT_ID,
                status="ACTIVE",
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
            )
            session.add(user)
        else:
            # A rerun must leave the documented demo credentials usable even
            # when the prior run used a different locally supplied password.
            user.password_hash = password_hash
            user.display_name = spec.display_name
            user.department_id = DEMO_TENANT_ID
            user.status = "ACTIVE"
            user.login_failed_count = 0
            user.locked_until = None
            user.deleted_at = None
        users[spec.key] = user
    await session.flush()
    return users


async def _seed_demo_department(session: AsyncSession) -> None:
    await _add_if_missing(
        session,
        Department(
            id=DEMO_TENANT_ID,
            code="DEMO",
            name="ST-702 演示租户",
            path="/DEMO",
            status="ACTIVE",
            created_at=DEMO_TIME,
            updated_at=DEMO_TIME,
        ),
    )


async def _seed_resource_grants(
    session: AsyncSession, users: dict[str, User], roles: dict[str, Role]
) -> None:
    grants = (
        ("USER", users["user"].id, "KNOWLEDGE_BASE", KNOWLEDGE_BASE_ID),
        ("USER", users["user"].id, "MERCHANT", MERCHANT_QINGHE_ID),
        ("ROLE", roles["MERCHANT_ADMIN"].id, "MERCHANT", MERCHANT_QINGHE_ID),
        ("ROLE", roles["MERCHANT_ADMIN"].id, "MERCHANT", MERCHANT_SHUXIANG_ID),
    )
    for offset, (subject_type, subject_id, resource_type, resource_id) in enumerate(
        grants, start=1
    ):
        exists = await session.scalar(
            select(ResourceGrant.id).where(
                ResourceGrant.subject_type == subject_type,
                ResourceGrant.subject_id == subject_id,
                ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
                ResourceGrant.action == "READ",
            )
        )
        if exists is None:
            session.add(
                ResourceGrant(
                    id=UUID(f"70200000-0000-4000-8000-0000000000{80 + offset}"),
                    subject_type=subject_type,
                    subject_id=subject_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    action="READ",
                    created_at=DEMO_TIME,
                    updated_at=DEMO_TIME,
                )
            )


async def _seed_knowledge(session: AsyncSession, admin: User) -> None:
    await _add_if_missing(
        session,
        ModelDefinition(
            id=MODEL_DEFINITION_ID,
            code="demo-sentiment",
            name="演示情感分析模型",
            task_type="sentiment",
            provider="local-deterministic",
            created_at=DEMO_TIME,
            updated_at=DEMO_TIME,
        ),
    )
    for model_id, version, status in (
        (MODEL_VERSION_V1_ID, "demo-sentiment-v1", "ARCHIVED"),
        (MODEL_VERSION_V2_ID, "demo-sentiment-v2", "APPROVED"),
    ):
        await _add_if_missing(
            session,
            ModelVersion(
                id=model_id,
                model_definition_id=MODEL_DEFINITION_ID,
                version=version,
                base_model_ref="local-deterministic-v1",
                adapter_uri=f"demo://models/{version}",
                artifact_sha256=_sha256(version),
                dimension=512,
                labels_json=["POSITIVE", "NEUTRAL", "NEGATIVE"],
                metrics_json={"accuracy": 0.95, "fixture": "st-702"},
                status=status,
                created_by=admin.id,
                created_at=DEMO_TIME,
            ),
        )
    await _add_if_missing(
        session,
        KnowledgeBase(
            id=KNOWLEDGE_BASE_ID,
            tenant_id=DEMO_TENANT_ID,
            department_id=DEMO_TENANT_ID,
            owner_id=admin.id,
            name="ST-702 探店演示知识库",
            normalized_name="st-702 探店演示知识库",
            description="固定商家资料，用于 RAG、引用跳转和无结果兜底演示。",
            embedding_model_version_id=MODEL_VERSION_V2_ID,
            chunk_size=500,
            chunk_overlap=80,
            status="ACTIVE",
            created_at=DEMO_TIME,
            updated_at=DEMO_TIME,
        ),
    )
    await session.flush()

    document_content = (
        (
            DOCUMENT_QINGHE_ID,
            DOCUMENT_QINGHE_VERSION_ID,
            CHUNK_QINGHE_ID,
            "merchant-qinghe.md",
            "清河面馆探店资料",
            "清河面馆位于演示街区，午餐适合两人同行。招牌牛肉面与双人小菜套餐分量充足。"
            "工作日 11:30 至 12:30 排队较多，建议错峰到店；门店环境简洁，服务员会主动安排拼桌。",
            MERCHANT_QINGHE_ID,
            "清河面馆",
        ),
        (
            DOCUMENT_SHUXIANG_ID,
            DOCUMENT_SHUXIANG_VERSION_ID,
            CHUNK_SHUXIANG_ID,
            "merchant-shuxiang.md",
            "书香咖啡馆探店资料",
            "书香咖啡馆提供靠窗安静座位、充足插座和稳定工作日网络，适合办公与小型会议。"
            "周末 14:00 至 16:00 客流较高，咖啡和甜点需要等候；请优先预约安静区域。",
            MERCHANT_SHUXIANG_ID,
            "书香咖啡馆",
        ),
    )
    for (
        document_id,
        version_id,
        chunk_id,
        source_key,
        display_name,
        content,
        merchant_id,
        merchant_name,
    ) in document_content:
        await _add_if_missing(
            session,
            Document(
                id=document_id,
                knowledge_base_id=KNOWLEDGE_BASE_ID,
                source_type="DEMO",
                source_key=source_key,
                display_name=display_name,
                mime_type="text/markdown",
                status="READY",
                current_version_no=1,
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
            ),
        )
        await _add_if_missing(
            session,
            DocumentVersion(
                id=version_id,
                document_id=document_id,
                version_no=1,
                file_uri=f"demo://knowledge/{source_key}",
                file_sha256=_sha256(content),
                file_size=len(content.encode("utf-8")),
                parser_name="demo-seed",
                parser_version="1.0",
                cleaning_config_json={"fixture": "st-702"},
                splitter_config_json={"chunk_size": 500, "overlap": 80},
                is_current=True,
                created_at=DEMO_TIME,
            ),
        )
        await _add_if_missing(
            session,
            Chunk(
                id=chunk_id,
                document_version_id=version_id,
                chunk_no=1,
                content=content,
                content_hash=_sha256(content),
                token_count=len(content),
                page_number=1,
                metadata_json={
                    "merchant_id": str(merchant_id),
                    "merchant_name": merchant_name,
                    "source_url": f"/app/documents/{document_id}",
                },
                embedding_model_version_id=MODEL_VERSION_V2_ID,
                opensearch_document_id=f"demo-{document_id}",
                index_status="INDEXED",
                indexed_at=DEMO_TIME,
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
            ),
        )


async def _seed_reviews(session: AsyncSession) -> None:
    for row in _review_rows():
        await _add_if_missing(
            session,
            ReviewAnalysis(
                id=UUID(str(row["id"])),
                merchant_id=str(row["merchant_id"]),
                review_text=str(row["review_text"]),
                sentiment=str(row["sentiment"]),
                confidence=float(row["confidence"]),
                model_version="demo-sentiment-v2",
                aspect_labels=json.dumps(row["aspects"], ensure_ascii=False),
                negative_reasons=json.dumps(row["reasons"], ensure_ascii=False),
                review_date=row["date"],  # type: ignore[arg-type]
                created_at=DEMO_TIME,
                updated_at=DEMO_TIME,
            ),
        )


async def _seed_feedback(session: AsyncSession, user: User) -> None:
    await _add_if_missing(
        session,
        Conversation(
            id=CONVERSATION_ID,
            owner_user_id=user.id,
            title="清河面馆午餐咨询",
            status="ACTIVE",
            memory_backend="MYSQL",
            settings_json={"fixture": "st-702"},
            created_at=DEMO_TIME,
            updated_at=DEMO_TIME,
        ),
    )
    await _add_if_missing(
        session,
        Message(
            id=USER_MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            sequence_no=1,
            request_id="st-702-demo-question",
            role="USER",
            content="清河面馆适合两个人午餐吗？",
            status="COMPLETED",
            created_at=DEMO_TIME,
        ),
    )
    await _add_if_missing(
        session,
        Message(
            id=ASSISTANT_MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            parent_message_id=USER_MESSAGE_ID,
            sequence_no=2,
            request_id="st-702-demo-answer",
            role="ASSISTANT",
            content="适合。资料显示双人小菜套餐分量充足；午餐高峰建议错峰以避开排队。",
            status="COMPLETED",
            model_version_id=MODEL_VERSION_V2_ID,
            prompt_tokens=24,
            completion_tokens=36,
            latency_ms=120,
            created_at=DEMO_TIME,
        ),
    )
    await session.flush()
    conversation = await session.get(Conversation, CONVERSATION_ID)
    if conversation is None:
        raise RuntimeError("seeded conversation was not persisted")
    conversation.current_branch_message_id = ASSISTANT_MESSAGE_ID
    conversation.updated_at = DEMO_TIME
    if await session.get(MessageSource, (ASSISTANT_MESSAGE_ID, CHUNK_QINGHE_ID)) is None:
        session.add(
            MessageSource(
                message_id=ASSISTANT_MESSAGE_ID,
                chunk_id=CHUNK_QINGHE_ID,
                rank_no=1,
                score=0.98,
                raw_score=0.98,
                source_location_snapshot="清河面馆探店资料",
                content_snapshot="双人小菜套餐分量充足；午餐高峰建议错峰。",
            )
        )
    if await _add_if_missing(
        session,
        Feedback(
            id=FEEDBACK_ID,
            user_id=user.id,
            message_id=ASSISTANT_MESSAGE_ID,
            rating=1,
            correction=None,
            reason_codes_json=["HELPFUL"],
            pii_flagged=False,
            review_status="PENDING_REVIEW",
            created_at=DEMO_TIME,
            updated_at=DEMO_TIME,
        ),
    ):
        session.add(
            FeedbackAudit(
                id=FEEDBACK_AUDIT_ID,
                feedback_id=FEEDBACK_ID,
                version_no=1,
                rating=1,
                correction_snapshot=None,
                reason_codes_snapshot=["HELPFUL"],
                changed_by=user.id,
                changed_at=DEMO_TIME,
            )
        )


async def seed_demo_data(session: AsyncSession, *, password: str) -> DemoSeedSummary:
    """Insert the ST-702 fixture into an existing, migrated database."""

    if not password:
        raise ValueError("demo seed password must not be blank")
    await _seed_demo_department(session)
    users = await _seed_users(session, password)
    roles = await _seed_roles_and_permissions(session, users)
    await _seed_knowledge(session, users["admin"])
    await _seed_resource_grants(session, users, roles)
    await _seed_reviews(session)
    await _seed_feedback(session, users["user"])
    await _add_if_missing(
        session,
        ModelDeployment(
            id=UUID("70200000-0000-4000-8000-000000000090"),
            scene="sentiment",
            environment="demo",
            model_version_id=MODEL_VERSION_V2_ID,
            traffic_percent=100,
            action="FULL",
            status="ACTIVE",
            result="SUCCEEDED",
            deployed_by=users["admin"].id,
            reason="ST-702 deterministic demo baseline",
            created_at=DEMO_TIME,
        ),
    )
    return DemoSeedSummary(
        users=len(DEMO_USERS),
        merchants=2,
        reviews=len(_review_rows()),
        documents=2,
        questions=len(DEMO_QUESTIONS),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed deterministic ST-702 demo data.")
    parser.add_argument(
        "--password-env",
        default="DEMO_SEED_PASSWORD",
        help="Environment variable containing the shared demo-account password.",
    )
    return parser


def _password_from_environment(variable_name: str) -> str:
    password = os.environ.get(variable_name, "")
    if not password:
        raise ValueError(f"environment variable {variable_name!r} must contain the demo password")
    return password


async def _run(password: str) -> DemoSeedSummary:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with AsyncSession(engine) as session, session.begin():
            return await seed_demo_data(session, password=password)
    finally:
        await engine.dispose()


def main() -> None:
    args = _parser().parse_args()
    try:
        summary = asyncio.run(_run(_password_from_environment(args.password_env)))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "ST-702 demo data ready: "
        f"{summary.users} users, {summary.merchants} merchants, {summary.reviews} reviews, "
        f"{summary.documents} documents, {summary.questions} standard questions."
    )


if __name__ == "__main__":
    main()
