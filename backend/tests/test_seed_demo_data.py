import json
from uuid import UUID

import pytest

from app.cli.seed_demo_data import (
    CHAT_MODEL_DEPLOYMENT_ID,
    CHAT_MODEL_VERSION,
    CHAT_MODEL_VERSION_ID,
    CHUNK_QINGHE_ID,
    CHUNK_SHUXIANG_ID,
    DEMO_KNOWLEDGE_ROLE_CODES,
    DEMO_QUESTIONS,
    DEMO_USERS,
    QUESTION_SET_PATH,
    _parser,
    _password_from_environment,
    _project_demo_facts,
    _review_rows,
)
from app.etl.models import ChunkRecord
from app.operations.storage_recovery import ChunkFact


def test_demo_seed_fixture_has_stable_core_coverage() -> None:
    reviews = _review_rows()

    assert [user.username for user in DEMO_USERS] == ["demo-admin", "demo-user", "demo-merchant"]
    assert len(reviews) == 12
    assert {row["sentiment"] for row in reviews} == {"POSITIVE", "NEUTRAL", "NEGATIVE"}
    assert len({row["merchant_id"] for row in reviews}) == 2
    assert all(UUID(str(row["id"])) for row in reviews)
    assert DEMO_QUESTIONS[-1]["expected_fallback"] is True
    assert CHAT_MODEL_VERSION == "local-extractive-rag-v1"
    assert CHAT_MODEL_VERSION_ID != CHAT_MODEL_DEPLOYMENT_ID
    assert DEMO_KNOWLEDGE_ROLE_CODES == ("USER", "MERCHANT_ADMIN", "PLATFORM_ADMIN")


def test_question_file_matches_the_seeded_question_set() -> None:
    payload = json.loads(QUESTION_SET_PATH.read_text(encoding="utf-8"))

    assert payload["suite"] == "st-702-demo-questions-v1"
    assert payload["questions"] == list(DEMO_QUESTIONS)


def test_demo_seed_password_is_read_from_a_named_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ST_702_TEST_PASSWORD", "local-only-password")

    assert _password_from_environment("ST_702_TEST_PASSWORD") == "local-only-password"
    assert _parser().parse_args([]).password_env == "DEMO_SEED_PASSWORD"
    assert _parser().parse_args([]).repair_chat_runtime is False
    assert _parser().parse_args(["--repair-chat-runtime"]).repair_chat_runtime is True


def test_demo_seed_rejects_missing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ST_702_MISSING_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="ST_702_MISSING_PASSWORD"):
        _password_from_environment("ST_702_MISSING_PASSWORD")


class RecordingProjection:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int]] = []

    def upsert(self, version_id: UUID, chunks: list[ChunkRecord]) -> None:
        self.calls.append((version_id, len(chunks)))


def _chunk_fact(chunk_id: UUID, version_id: UUID) -> ChunkFact:
    return ChunkFact(
        chunk_id=chunk_id,
        tenant_id=UUID("70200000-0000-4000-8000-000000000001"),
        knowledge_base_id=UUID("70200000-0000-4000-8000-000000000010"),
        document_id=UUID("70200000-0000-4000-8000-000000000040"),
        document_version_id=version_id,
        chunk_no=0,
        content="演示资料",
        content_hash="a" * 64,
        token_count=4,
        page_number=1,
        source_key="demo.md",
        source_type="MD",
        metadata={},
        stored_projection_id="legacy-id",
    )


def test_demo_seed_projects_both_search_chunks() -> None:
    qinghe_version = UUID("70200000-0000-4000-8000-000000000042")
    shuxiang_version = UUID("70200000-0000-4000-8000-000000000043")
    projection = RecordingProjection()

    projected = _project_demo_facts(
        [
            _chunk_fact(CHUNK_QINGHE_ID, qinghe_version),
            _chunk_fact(CHUNK_SHUXIANG_ID, shuxiang_version),
        ],
        projection,
    )

    assert {fact.chunk_id for fact in projected} == {CHUNK_QINGHE_ID, CHUNK_SHUXIANG_ID}
    assert projection.calls == [(qinghe_version, 1), (shuxiang_version, 1)]


def test_demo_seed_refuses_incomplete_search_projection() -> None:
    qinghe_version = UUID("70200000-0000-4000-8000-000000000042")

    with pytest.raises(RuntimeError, match="demo search chunks are missing"):
        _project_demo_facts([_chunk_fact(CHUNK_QINGHE_ID, qinghe_version)], RecordingProjection())
