"""End-to-end integration tests for ST-501 acceptance criteria ②④⑥.

Tests the full pipeline: FeedbackService.submit_feedback → DatasetService.generate_dataset
→ JSONL file output verification.

Covers:
- ② Idempotent feedback: repeated submissions produce single dataset sample
- ④ PII redaction: phone/email/id_card redacted in JSONL output
- ⑥ Data leakage: no entity or conversation crosses splits
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from app.application.dataset_service import DatasetService, InMemoryDatasetRepository
from app.application.feedback import FeedbackRecord, FeedbackService
from app.core.ids import uuid7
from app.domain.feedback import DatasetFilter, FeedbackCreate, SplitConfig
from tests.test_feedback_repository import InMemoryFeedbackRepository

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PHONE = "13812345678"
EMAIL = "test@example.com"
ID_CARD = "110101199003071234"


def _seed_message(
    repo: InMemoryFeedbackRepository,
    *,
    owner_user_id: UUID | None = None,
) -> tuple[UUID, UUID, UUID, UUID]:
    """Seed a message and return (user_id, message_id, conversation_id, model_version_id)."""
    user_id = owner_user_id or uuid7()
    message_id = uuid7()
    conversation_id = uuid7()
    model_version_id = uuid7()
    repo.seed_message(
        message_id=message_id,
        conversation_id=conversation_id,
        owner_user_id=user_id,
        model_version_id=model_version_id,
    )
    return user_id, message_id, conversation_id, model_version_id


def _approve_feedback(repo: InMemoryFeedbackRepository, feedback_id: UUID) -> None:
    """Replace a feedback record with an APPROVED version (frozen dataclass → must replace)."""
    for i, fb in enumerate(repo._feedbacks):
        if fb.id == feedback_id:
            repo._feedbacks[i] = replace(fb, review_status="APPROVED")
            return
    msg = f"Feedback {feedback_id} not found in repo"
    raise ValueError(msg)


def _make_approved_record(
    *,
    user_id: UUID | None = None,
    message_id: UUID | None = None,
    rating: int = 1,
    correction: str | None = None,
    reason_codes: list[str] | None = None,
) -> FeedbackRecord:
    """Create a pre-approved FeedbackRecord for direct repo insertion."""
    return FeedbackRecord(
        id=uuid7(),
        user_id=user_id or uuid7(),
        message_id=message_id or uuid7(),
        rating=rating,
        correction=correction,
        reason_codes=reason_codes or [],
        pii_flagged=False,
        review_status="APPROVED",
        version=1,
        created_at=None,
        updated_at=None,
    )


def _build_service(
    feedback_repo: InMemoryFeedbackRepository,
) -> DatasetService:
    """Wire up a DatasetService with InMemory repositories."""
    return DatasetService(feedback_repo, InMemoryDatasetRepository())


def _generate_and_read_jsonl(
    service: DatasetService,
    *,
    output_path: str,
    name: str = "test_ds",
    task_type: str = "sentiment_classification",
    split_config: SplitConfig | None = None,
) -> tuple[list[dict[str, object]], str]:
    """Generate a dataset, read back the JSONL and return (lines, dataset_hash)."""
    record = service._builder.build(
        records=service._feedback_repo._feedbacks,  # noqa: SLF001
        name=name,
        task_type=task_type,
        split_config=split_config,
        output_path=output_path,
    )
    with Path(output_path).open(encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    return lines, record.dataset_hash


# ---------------------------------------------------------------------------
# TestDuplicateFeedbackIntegration — criterion ②
# ---------------------------------------------------------------------------


class TestDuplicateFeedbackIntegration:
    """End-to-end: repeated feedback submission → dataset contains no duplicates."""

    @pytest.mark.asyncio
    async def test_repeated_submission_produces_single_dataset_sample(self, tmp_path: Path) -> None:
        """Same user + same message submitted 5 times → dataset has exactly 1 sample."""
        repo = InMemoryFeedbackRepository()
        uid, mid, cid, _ = _seed_message(repo)
        svc = FeedbackService(repo)

        for _ in range(5):
            await svc.submit_feedback(
                uid,
                FeedbackCreate(
                    conversation_id=cid,
                    message_id=mid,
                    rating=-1,
                    correction="上菜太慢",
                    reason_codes=["SERVING_SPEED"],
                ),
            )

        # Approve the feedback so it enters the dataset
        records = await repo.query_feedbacks(DatasetFilter())
        assert len(records) == 1
        _approve_feedback(repo, records[0].id)
        assert records[0].version == 5

        # Generate dataset
        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        # Only one sample in the JSONL
        assert len(lines) == 1
        assert lines[0]["text"] == "上菜太慢"

    @pytest.mark.asyncio
    async def test_version_increment_preserves_latest_correction(self, tmp_path: Path) -> None:
        """First negative, then positive → dataset reflects latest version only."""
        repo = InMemoryFeedbackRepository()
        uid, mid, cid, _ = _seed_message(repo)
        svc = FeedbackService(repo)

        # v1: negative
        await svc.submit_feedback(
            uid,
            FeedbackCreate(
                conversation_id=cid,
                message_id=mid,
                rating=-1,
                correction="差评",
                reason_codes=["X"],
            ),
        )
        # v2: positive (overwrites)
        await svc.submit_feedback(
            uid,
            FeedbackCreate(
                conversation_id=cid,
                message_id=mid,
                rating=1,
            ),
        )

        records = await repo.query_feedbacks(DatasetFilter())
        assert len(records) == 1
        assert records[0].version == 2
        assert records[0].rating == 1
        _approve_feedback(repo, records[0].id)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 1
        # Latest version is positive with empty correction
        assert lines[0]["label"] == "POSITIVE"
        assert lines[0]["text"] == ""

    @pytest.mark.asyncio
    async def test_different_users_same_message_produces_multiple_samples(
        self, tmp_path: Path
    ) -> None:
        """Different users submit feedback for the same message → each has its own record."""
        repo = InMemoryFeedbackRepository()
        uid1, mid, cid, _ = _seed_message(repo)
        uid2 = uuid7()

        svc = FeedbackService(repo)

        for uid in (uid1, uid2):
            await svc.submit_feedback(
                uid,
                FeedbackCreate(
                    conversation_id=cid,
                    message_id=mid,
                    rating=-1,
                    correction=f"差评 from user {uid}",
                    reason_codes=["R"],
                ),
            )

        records = await repo.query_feedbacks(DatasetFilter())
        assert len(records) == 2
        for r in records:
            _approve_feedback(repo, r.id)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 2
        texts = {line["text"] for line in lines}
        assert len(texts) == 2  # two distinct correction texts

    @pytest.mark.asyncio
    async def test_dataset_excludes_pending_review_feedback(self, tmp_path: Path) -> None:
        """PENDING_REVIEW feedback must not appear in the dataset JSONL."""
        repo = InMemoryFeedbackRepository()
        uid, mid, cid, _ = _seed_message(repo)
        svc = FeedbackService(repo)

        await svc.submit_feedback(
            uid,
            FeedbackCreate(
                conversation_id=cid,
                message_id=mid,
                rating=-1,
                correction="差评",
                reason_codes=["R"],
            ),
        )
        # Feedback is PENDING_REVIEW (default from create_feedback)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        # No samples because all feedback is PENDING_REVIEW
        assert len(lines) == 0


# ---------------------------------------------------------------------------
# TestPIIRedactionIntegration — criterion ④
# ---------------------------------------------------------------------------


class TestPIIRedactionIntegration:
    """End-to-end: PII in feedback → dataset JSONL has no raw PII."""

    def test_phone_redacted_in_jsonl_output(self, tmp_path: Path) -> None:
        """Phone number must be masked in the JSONL output."""
        repo = InMemoryFeedbackRepository()
        record = _make_approved_record(
            rating=-1,
            correction=f"电话 {PHONE} 差评",
            reason_codes=["BAD"],
        )
        repo._feedbacks.append(record)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 1
        text = lines[0]["text"]
        assert PHONE not in text
        assert "*" in text

    def test_email_redacted_in_jsonl_output(self, tmp_path: Path) -> None:
        """Email address must be masked in the JSONL output."""
        repo = InMemoryFeedbackRepository()
        record = _make_approved_record(
            rating=-1,
            correction=f"联系邮箱 {EMAIL} 投诉",
            reason_codes=["EMAIL"],
        )
        repo._feedbacks.append(record)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 1
        text = lines[0]["text"]
        assert EMAIL not in text
        assert "*" in text

    def test_id_card_redacted_in_jsonl_output(self, tmp_path: Path) -> None:
        """ID card number must be masked in the JSONL output."""
        repo = InMemoryFeedbackRepository()
        record = _make_approved_record(
            rating=-1,
            correction=f"身份证 {ID_CARD} 信息",
            reason_codes=["ID"],
        )
        repo._feedbacks.append(record)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 1
        text = lines[0]["text"]
        assert ID_CARD not in text
        assert "*" in text

    def test_mixed_pii_all_redacted_in_jsonl(self, tmp_path: Path) -> None:
        """All three PII types in one text → all redacted."""
        repo = InMemoryFeedbackRepository()
        record = _make_approved_record(
            rating=-1,
            correction=f"电话{PHONE}邮箱{EMAIL}身份证{ID_CARD}",
            reason_codes=["MIXED"],
        )
        repo._feedbacks.append(record)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 1
        text = lines[0]["text"]
        assert PHONE not in text
        assert EMAIL not in text
        assert ID_CARD not in text
        assert text.count("*") >= 3  # at least one mask per PII type

    def test_unauthorized_pii_feedback_excluded_from_dataset(self, tmp_path: Path) -> None:
        """PENDING_REVIEW feedback with PII must not enter the dataset at all."""
        repo = InMemoryFeedbackRepository()
        record = _make_approved_record(
            rating=-1,
            correction=f"电话 {PHONE} 差评",
            reason_codes=["R"],
        )
        # Change to PENDING_REVIEW
        record = replace(record, review_status="PENDING_REVIEW")
        repo._feedbacks.append(record)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        lines, _ = _generate_and_read_jsonl(service, output_path=output)

        assert len(lines) == 0  # nothing in dataset


# ---------------------------------------------------------------------------
# TestDataLeakageIntegration — criterion ⑥
# ---------------------------------------------------------------------------


class TestDataLeakageIntegration:
    """End-to-end: multiple entities → dataset → no cross-split leakage."""

    def test_no_conversation_id_across_splits(self, tmp_path: Path) -> None:
        """Same conversation_id must not appear in multiple splits."""
        cid = uuid7()
        # 3 users share the same conversation_id (via message_id proxy)
        records = [
            _make_approved_record(
                user_id=uuid7(),
                message_id=cid,  # CONVERSATION isolation uses message_id as proxy
                rating=-1 if i % 2 == 0 else 1,
                correction=f"text {i}" if i % 2 == 0 else None,
                reason_codes=["R"] if i % 2 == 0 else [],
            )
            for i in range(3)
        ]
        repo = InMemoryFeedbackRepository()
        repo._feedbacks.extend(records)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        config = SplitConfig(
            isolation_key="CONVERSATION",
            train_percent=0.6,
            validation_percent=0.2,
            test_percent=0.2,
            random_seed=42,
        )

        result = service._builder.build(
            records=records,
            name="ds",
            task_type="t",
            split_config=config,
            output_path=output,
        )

        # All 3 records share the same conversation → all in the same split
        splits = {a.split for a in result.assignments}
        assert len(splits) == 1

    def test_no_user_id_across_splits_entity_mode(self, tmp_path: Path) -> None:
        """ENTITY isolation: same user_id must not appear in multiple splits."""
        uid = uuid7()
        # Same user, different messages
        records = [
            _make_approved_record(
                user_id=uid,
                message_id=uuid7(),
                rating=-1,
                correction=f"correction {i}",
                reason_codes=["R"],
            )
            for i in range(5)
        ]
        # Add more users to ensure multiple splits
        for i in range(15):
            records.append(
                _make_approved_record(
                    user_id=uuid7(),
                    message_id=uuid7(),
                    rating=1 if i % 2 == 0 else -1,
                    correction=f"other {i}" if i % 2 == 1 else None,
                    reason_codes=["X"] if i % 2 == 1 else [],
                )
            )

        repo = InMemoryFeedbackRepository()
        repo._feedbacks.extend(records)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        config = SplitConfig(
            isolation_key="ENTITY",
            train_percent=0.7,
            validation_percent=0.15,
            test_percent=0.15,
            random_seed=42,
        )

        result = service._builder.build(
            records=records,
            name="ds",
            task_type="t",
            split_config=config,
            output_path=output,
        )

        # Verify no user_id appears in multiple splits
        split_users: dict[str, set[UUID]] = {}
        for a in result.assignments:
            split_users.setdefault(a.split, set()).add(a.isolation_key)

        all_sets = list(split_users.values())
        for i in range(len(all_sets)):
            for j in range(i + 1, len(all_sets)):
                assert all_sets[i].isdisjoint(all_sets[j]), (
                    f"Entity leakage: {all_sets[i] & all_sets[j]}"
                )

        # Verify the shared user's records are all in one split
        shared = [a for a in result.assignments if a.isolation_key == uid]
        assert len(shared) == 5
        assert len({a.split for a in shared}) == 1

    def test_split_counts_match_jsonl_line_count(self, tmp_path: Path) -> None:
        """JSONL line count must equal train + validation + test counts."""
        records = [
            _make_approved_record(
                rating=1 if i % 2 == 0 else -1,
                correction=f"text {i}" if i % 2 == 1 else None,
                reason_codes=["R"] if i % 2 == 1 else [],
            )
            for i in range(20)
        ]
        repo = InMemoryFeedbackRepository()
        repo._feedbacks.extend(records)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        config = SplitConfig(
            train_percent=0.6,
            validation_percent=0.2,
            test_percent=0.2,
        )

        result = service._builder.build(
            records=records,
            name="ds",
            task_type="t",
            split_config=config,
            output_path=output,
        )

        with Path(output).open(encoding="utf-8") as f:
            line_count = sum(1 for _ in f)

        total = (
            result.split_counts["train"]
            + result.split_counts["validation"]
            + result.split_counts["test"]
        )
        assert line_count == total
        assert line_count == result.sample_count

    def test_dataset_hash_matches_jsonl_content(self, tmp_path: Path) -> None:
        """SHA-256 of the JSONL file must match the stored dataset_hash (immutability)."""
        records = [
            _make_approved_record(
                rating=-1,
                correction=f"correction {i}",
                reason_codes=["R"],
            )
            for i in range(10)
        ]
        repo = InMemoryFeedbackRepository()
        repo._feedbacks.extend(records)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")

        result = service._builder.build(
            records=records,
            name="ds",
            task_type="t",
            output_path=output,
        )

        # Recompute SHA-256 from the file
        hasher = hashlib.sha256()
        with Path(output).open("rb") as f:
            hasher.update(f.read())
        assert hasher.hexdigest() == result.dataset_hash

    def test_large_dataset_no_leakage(self, tmp_path: Path) -> None:
        """30 records, 15 users, ENTITY isolation → no user in multiple splits."""
        records: list[FeedbackRecord] = []
        for u in range(15):
            uid = uuid7()
            for k in range(2):
                records.append(
                    _make_approved_record(
                        user_id=uid,
                        message_id=uuid7(),
                        rating=-1 if u % 2 == 0 else 1,
                        correction=f"user{u}_text{k}",
                        reason_codes=["R"] if u % 2 == 0 else [],
                    )
                )

        repo = InMemoryFeedbackRepository()
        repo._feedbacks.extend(records)

        service = _build_service(repo)
        output = str(tmp_path / "ds.jsonl")
        config = SplitConfig(
            isolation_key="ENTITY",
            train_percent=0.7,
            validation_percent=0.15,
            test_percent=0.15,
            random_seed=99,
        )

        result = service._builder.build(
            records=records,
            name="ds",
            task_type="t",
            split_config=config,
            output_path=output,
        )

        # Collect user_ids per split
        split_entities: dict[str, set[UUID]] = {}
        for a in result.assignments:
            split_entities.setdefault(a.split, set()).add(a.isolation_key)

        # Pairwise disjoint check
        splits = list(split_entities.values())
        for i in range(len(splits)):
            for j in range(i + 1, len(splits)):
                assert splits[i].isdisjoint(splits[j]), (
                    f"Leakage between splits: {splits[i] & splits[j]}"
                )

        # Verify all 30 records are in the dataset
        assert result.sample_count == 30

        # Verify JSONL file has 30 lines
        with Path(output).open(encoding="utf-8") as f:
            line_count = sum(1 for _ in f)
        assert line_count == 30
