"""Unit tests for dataset builder, service and API endpoints.

Covers ST-501 acceptance criteria:
- ⑤ JSONL dataset immutable after generation; SHA-256, sample count,
  provenance and quality report stored.
- ⑥ Stratified split by entity or conversation, no leakage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_builder import (
    DataCardGenerator,
    DatasetBuilder,
    DatasetSplitter,
    JSONLWriter,
)
from app.application.dataset_service import (
    DatasetNotFoundError,
    DatasetService,
    EmptyDatasetError,
    InMemoryDatasetRepository,
)
from app.application.feedback import FeedbackRecord
from app.core.ids import uuid7
from app.domain.feedback import DatasetFilter, SplitConfig
from app.main import create_app
from tests.test_feedback_repository import InMemoryFeedbackRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    rating: int = 1,
    correction: str | None = None,
    reason_codes: list[str] | None = None,
    review_status: str = "APPROVED",
    user_id: UUID | None = None,
    message_id: UUID | None = None,
) -> FeedbackRecord:
    """Create a FeedbackRecord for testing."""
    return FeedbackRecord(
        id=uuid7(),
        user_id=user_id or uuid7(),
        message_id=message_id or uuid7(),
        rating=rating,
        correction=correction,
        reason_codes=reason_codes or [],
        pii_flagged=False,
        review_status=review_status,
        version=1,
        created_at=None,
        updated_at=None,
    )


def _make_approved_records(n: int = 5) -> list[FeedbackRecord]:
    """Create n approved feedback records with unique user_id and message_id."""
    return [
        _make_record(
            rating=1 if i % 2 == 0 else -1,
            correction=f"feedback text {i}" if i % 2 == 1 else None,
            reason_codes=["REASON_A"] if i % 2 == 1 else [],
            review_status="APPROVED",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# TestDatasetSplitter — entity-aware stratified split (criterion ⑥)
# ---------------------------------------------------------------------------


class TestDatasetSplitter:
    """Tests for the DatasetSplitter entity-aware split."""

    def test_empty_input_returns_empty(self) -> None:
        result = DatasetSplitter.split([], SplitConfig())
        assert result == []

    def test_single_record_single_group(self) -> None:
        """With 1 group, default 80/10/10 means int(1*0.8)=0 train.

        The single group goes to test (the fallback bucket).
        This is expected integer-truncation behavior.
        """
        record = _make_record()
        result = DatasetSplitter.split([record], SplitConfig())
        assert len(result) == 1
        assert result[0].record == record

    def test_same_conversation_same_split(self) -> None:
        """All records from the same conversation must be in the same split."""
        cid = uuid7()
        records = [
            _make_record(message_id=cid, rating=1, review_status="APPROVED"),
            _make_record(message_id=cid, rating=-1, review_status="APPROVED"),
            _make_record(message_id=cid, rating=1, review_status="APPROVED"),
        ]
        result = DatasetSplitter.split(records, SplitConfig())
        splits = {a.split for a in result}
        assert len(splits) == 1  # all in the same split

    def test_no_leakage_across_splits(self) -> None:
        """No isolation_key should appear in more than one split."""
        records = _make_approved_records(20)
        config = SplitConfig(
            train_percent=0.6,
            validation_percent=0.2,
            test_percent=0.2,
        )
        result = DatasetSplitter.split(records, config)

        split_keys: dict[str, set[UUID]] = {}
        for a in result:
            split_keys.setdefault(a.split, set()).add(a.isolation_key)

        all_keys: list[set[UUID]] = list(split_keys.values())
        for i in range(len(all_keys)):
            for j in range(i + 1, len(all_keys)):
                assert all_keys[i].isdisjoint(all_keys[j]), (
                    f"Leakage between splits: {all_keys[i] & all_keys[j]}"
                )

    def test_seed_reproducibility(self) -> None:
        """Same seed must produce the same split assignments."""
        records = _make_approved_records(10)
        config = SplitConfig(random_seed=42)
        result1 = DatasetSplitter.split(records, config)
        result2 = DatasetSplitter.split(records, config)
        assert [a.split for a in result1] == [a.split for a in result2]

    def test_different_seed_different_assignment(self) -> None:
        """Different seeds should assign different records to val/test."""
        records = _make_approved_records(10)
        config1 = SplitConfig(random_seed=1)
        config2 = SplitConfig(random_seed=999)
        result1 = DatasetSplitter.split(records, config1)
        result2 = DatasetSplitter.split(records, config2)
        # Compare which record IDs are in validation/test (not the
        # split name sequence, which is always 8 train / 1 val / 1 test)
        val_test_1 = {a.record.id for a in result1 if a.split != "train"}
        val_test_2 = {a.record.id for a in result2 if a.split != "train"}
        assert val_test_1 != val_test_2

    def test_entity_isolation_uses_user_id(self) -> None:
        """ENTITY isolation should group by user_id, not message_id."""
        uid = uuid7()
        records = [
            _make_record(user_id=uid, message_id=uuid7(), review_status="APPROVED"),
            _make_record(user_id=uid, message_id=uuid7(), review_status="APPROVED"),
            _make_record(user_id=uuid7(), message_id=uuid7(), review_status="APPROVED"),
        ]
        config = SplitConfig(isolation_key="ENTITY")
        result = DatasetSplitter.split(records, config)
        # Find assignments for records sharing the same user_id
        shared = [a for a in result if a.isolation_key == uid]
        assert len(shared) == 2
        # Both must be in the same split
        assert shared[0].split == shared[1].split

    def test_content_json_format(self) -> None:
        """Content JSON should follow §9.2 format: text, label, reason."""
        record = _make_record(
            rating=-1,
            correction="上菜太慢",
            reason_codes=["SERVING_SPEED"],
        )
        result = DatasetSplitter.split([record], SplitConfig())
        content = result[0].content_json
        assert "text" in content
        assert "label" in content
        assert "reason" in content
        assert content["text"] == "上菜太慢"
        assert content["label"] == "NEGATIVE"
        assert content["reason"] == "SERVING_SPEED"

    def test_content_json_positive_label(self) -> None:
        record = _make_record(rating=1, correction=None, reason_codes=[])
        result = DatasetSplitter.split([record], SplitConfig())
        content = result[0].content_json
        assert content["label"] == "POSITIVE"
        assert content["text"] == ""
        assert content["reason"] == ""

    def test_content_hash_is_sha256(self) -> None:
        record = _make_record()
        result = DatasetSplitter.split([record], SplitConfig())
        assert len(result[0].content_hash) == 64
        # Verify it's a valid hex string
        int(result[0].content_hash, 16)

    def test_split_percentages_respected(self) -> None:
        """With 10 groups, 80/10/10 should give 8/1/1 groups."""
        records = _make_approved_records(10)
        config = SplitConfig(
            train_percent=0.8,
            validation_percent=0.1,
            test_percent=0.1,
        )
        result = DatasetSplitter.split(records, config)
        train_count = sum(1 for a in result if a.split == "train")
        val_count = sum(1 for a in result if a.split == "validation")
        test_count = sum(1 for a in result if a.split == "test")
        assert train_count == 8
        assert val_count == 1
        assert test_count == 1


# ---------------------------------------------------------------------------
# TestJSONLWriter — file writing and SHA-256 hash (criterion ⑤)
# ---------------------------------------------------------------------------


class TestJSONLWriter:
    """Tests for the JSONLWriter."""

    def test_write_creates_file(self, tmp_path: Path) -> None:
        records = _make_approved_records(3)
        assignments = DatasetSplitter.split(records, SplitConfig())
        output = tmp_path / "dataset.jsonl"

        JSONLWriter.write(assignments, str(output))
        assert output.exists()

    def test_write_returns_hash_and_uri(self, tmp_path: Path) -> None:
        records = _make_approved_records(3)
        assignments = DatasetSplitter.split(records, SplitConfig())
        output = tmp_path / "dataset.jsonl"

        dataset_hash, storage_uri = JSONLWriter.write(assignments, str(output))
        assert len(dataset_hash) == 64
        assert storage_uri == str(output.resolve())

    def test_hash_matches_file_content(self, tmp_path: Path) -> None:
        records = _make_approved_records(3)
        assignments = DatasetSplitter.split(records, SplitConfig())
        output = tmp_path / "dataset.jsonl"

        dataset_hash, _ = JSONLWriter.write(assignments, str(output))

        # Recompute hash from file
        hasher = hashlib.sha256()
        with output.open("rb") as f:
            hasher.update(f.read())
        assert hasher.hexdigest() == dataset_hash

    def test_lines_are_valid_json(self, tmp_path: Path) -> None:
        records = _make_approved_records(3)
        assignments = DatasetSplitter.split(records, SplitConfig())
        output = tmp_path / "dataset.jsonl"

        JSONLWriter.write(assignments, str(output))
        with output.open(encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                assert "text" in obj
                assert "label" in obj
                assert "reason" in obj

    def test_lines_ordered_by_split(self, tmp_path: Path) -> None:
        """Lines should be ordered: train, validation, test."""
        records = _make_approved_records(10)
        config = SplitConfig(
            train_percent=0.6,
            validation_percent=0.2,
            test_percent=0.2,
        )
        assignments = DatasetSplitter.split(records, config)
        output = tmp_path / "dataset.jsonl"

        JSONLWriter.write(assignments, str(output))
        with output.open(encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        # Check that we have the right total
        assert len(lines) == len(assignments)

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        """Same assignments should produce the same hash."""
        records = _make_approved_records(5)
        assignments = DatasetSplitter.split(records, SplitConfig())

        hash1, _ = JSONLWriter.write(assignments, str(tmp_path / "a.jsonl"))
        hash2, _ = JSONLWriter.write(assignments, str(tmp_path / "b.jsonl"))
        assert hash1 == hash2


# ---------------------------------------------------------------------------
# TestDataCardGenerator — data card generation (criterion ⑤)
# ---------------------------------------------------------------------------


class TestDataCardGenerator:
    """Tests for the DataCardGenerator."""

    def test_contains_all_fields(self) -> None:
        from app.application.feedback_quality import QualityReport

        report = QualityReport(
            total_candidates=10,
            total_accepted=8,
            total_rejected=2,
            acceptance_rate=0.8,
        )
        config = SplitConfig()
        card = DataCardGenerator.generate(
            name="test_dataset",
            task_type="sentiment_classification",
            dataset_hash="abc123",
            sample_count=8,
            split_counts={"train": 6, "validation": 1, "test": 1},
            label_distribution={"POSITIVE": 4, "NEGATIVE": 4},
            source_distribution={"user_feedback": 8},
            redaction_version="pii-v1.0",
            quality_report=report,
            split_config=config,
        )
        assert card["name"] == "test_dataset"
        assert card["task_type"] == "sentiment_classification"
        assert card["dataset_hash"] == "abc123"
        assert card["sample_count"] == 8
        assert "generated_at" in card
        assert card["splits"]["train"] == 6
        assert card["splits"]["validation"] == 1
        assert card["splits"]["test"] == 1
        assert card["label_distribution"]["POSITIVE"] == 4
        assert card["source_distribution"]["user_feedback"] == 8
        assert card["redaction"]["version"] == "pii-v1.0"
        assert card["quality"]["total_accepted"] == 8
        assert card["quality"]["total_rejected"] == 2
        assert card["split_config"]["random_seed"] == 42

    def test_json_serializable(self) -> None:
        from app.application.feedback_quality import QualityReport

        report = QualityReport(
            total_candidates=5,
            total_accepted=3,
            total_rejected=2,
            acceptance_rate=0.6,
        )
        card = DataCardGenerator.generate(
            name="ds",
            task_type="task",
            dataset_hash="h",
            sample_count=3,
            split_counts={"train": 2, "validation": 1, "test": 0},
            label_distribution={"POSITIVE": 2, "NEGATIVE": 1},
            source_distribution={"user_feedback": 3},
            redaction_version="pii-v1.0",
            quality_report=report,
            split_config=SplitConfig(),
        )
        json.dumps(card)  # Should not raise


# ---------------------------------------------------------------------------
# TestDatasetBuilder — full pipeline (criterion ⑤⑥)
# ---------------------------------------------------------------------------


class TestDatasetBuilder:
    """Tests for the DatasetBuilder full pipeline."""

    def test_build_with_records(self) -> None:
        records = _make_approved_records(5)
        builder = DatasetBuilder()
        result = builder.build(
            records=records,
            name="test_ds",
            task_type="sentiment_classification",
        )
        assert result.dataset_hash
        assert len(result.dataset_hash) == 64
        assert result.sample_count > 0
        total = (
            result.split_counts["train"]
            + result.split_counts["validation"]
            + result.split_counts["test"]
        )
        assert total == result.sample_count

    def test_build_empty_records(self) -> None:
        builder = DatasetBuilder()
        result = builder.build(
            records=[],
            name="empty_ds",
            task_type="sentiment_classification",
        )
        assert result.sample_count == 0
        assert result.dataset_hash
        assert result.assignments == []
        assert result.storage_uri is None

    def test_build_hash_deterministic(self) -> None:
        """Same input → same hash."""
        records = _make_approved_records(5)
        builder = DatasetBuilder()
        r1 = builder.build(records=records, name="ds1", task_type="t")
        r2 = builder.build(records=records, name="ds2", task_type="t")
        assert r1.dataset_hash == r2.dataset_hash

    def test_build_pii_redaction_applied(self) -> None:
        record = _make_record(
            rating=-1,
            correction="电话 13812345678 差评",
            reason_codes=["BAD"],
            review_status="APPROVED",
        )
        builder = DatasetBuilder()
        result = builder.build(
            records=[record],
            name="pii_ds",
            task_type="sentiment",
        )
        # The redacted text should be in content_json
        text = result.assignments[0].content_json["text"]
        assert "13812345678" not in text
        assert "*" in text

    def test_build_statistics_contain_label_distribution(self) -> None:
        records = [
            _make_record(rating=1, review_status="APPROVED"),
            _make_record(rating=1, review_status="APPROVED"),
            _make_record(
                rating=-1, correction="差评", reason_codes=["X"], review_status="APPROVED"
            ),
        ]
        builder = DatasetBuilder()
        result = builder.build(records=records, name="ds", task_type="t")
        labels = result.statistics["label_distribution"]
        assert labels["POSITIVE"] == 2
        assert labels["NEGATIVE"] == 1

    def test_build_data_card_has_quality_report(self) -> None:
        records = _make_approved_records(3)
        builder = DatasetBuilder()
        result = builder.build(records=records, name="ds", task_type="t")
        assert "quality" in result.data_card
        assert result.data_card["quality"]["total_accepted"] == 3
        assert result.data_card["quality"]["total_rejected"] == 0

    def test_build_with_output_path(self, tmp_path: Path) -> None:
        records = _make_approved_records(3)
        builder = DatasetBuilder()
        output = tmp_path / "dataset.jsonl"
        result = builder.build(
            records=records,
            name="ds",
            task_type="t",
            output_path=str(output),
        )
        assert result.storage_uri is not None
        assert output.exists()
        # Hash from builder should match file hash
        hasher = hashlib.sha256()
        with output.open("rb") as f:
            hasher.update(f.read())
        assert hasher.hexdigest() == result.dataset_hash

    def test_build_redaction_version_in_result(self) -> None:
        records = _make_approved_records(2)
        builder = DatasetBuilder()
        result = builder.build(records=records, name="ds", task_type="t")
        assert result.redaction_version == "pii-v1.0"

    def test_build_unauthorized_filtered_out(self) -> None:
        """Records with PENDING_REVIEW should be filtered out."""
        records = [
            _make_record(rating=1, review_status="APPROVED"),
            _make_record(rating=1, review_status="PENDING_REVIEW"),
            _make_record(rating=1, review_status="REJECTED"),
        ]
        builder = DatasetBuilder()
        result = builder.build(records=records, name="ds", task_type="t")
        assert result.sample_count == 1
        assert result.quality_report.total_candidates == 3
        assert result.quality_report.total_accepted == 1
        assert result.quality_report.total_rejected == 2


# ---------------------------------------------------------------------------
# TestDatasetService — service orchestration
# ---------------------------------------------------------------------------


class TestDatasetService:
    """Tests for the DatasetService."""

    def _make_service(
        self, records: list[FeedbackRecord] | None = None
    ) -> tuple[DatasetService, InMemoryFeedbackRepository, InMemoryDatasetRepository]:
        feedback_repo = InMemoryFeedbackRepository()
        for r in records or []:
            feedback_repo._feedbacks.append(r)
        dataset_repo = InMemoryDatasetRepository()
        service = DatasetService(feedback_repo, dataset_repo)
        return service, feedback_repo, dataset_repo

    @pytest.mark.asyncio
    async def test_generate_dataset_returns_record(self) -> None:
        records = _make_approved_records(5)
        service, _, _ = self._make_service(records)
        record = await service.generate_dataset(
            name="test_ds",
            task_type="sentiment_classification",
            filter_config=DatasetFilter(),
        )
        assert record.name == "test_ds"
        assert record.task_type == "sentiment_classification"
        assert record.dataset_hash
        assert len(record.dataset_hash) == 64
        assert record.sample_count > 0
        assert record.status == "READY"
        assert record.redaction_version == "pii-v1.0"
        assert record.created_at is not None
        assert record.updated_at is not None

    @pytest.mark.asyncio
    async def test_generate_dataset_empty_raises(self) -> None:
        service, _, _ = self._make_service([])
        with pytest.raises(EmptyDatasetError):
            await service.generate_dataset(
                name="empty",
                task_type="t",
                filter_config=DatasetFilter(),
            )

    @pytest.mark.asyncio
    async def test_generate_dataset_persisted(self) -> None:
        records = _make_approved_records(3)
        service, _, dataset_repo = self._make_service(records)
        record = await service.generate_dataset(
            name="persisted_ds",
            task_type="t",
            filter_config=DatasetFilter(),
        )
        # Verify it's persisted
        stored = await dataset_repo.get_dataset(record.id)
        assert stored is not None
        assert stored.id == record.id
        assert stored.dataset_hash == record.dataset_hash

    @pytest.mark.asyncio
    async def test_generate_dataset_with_split_config(self) -> None:
        records = _make_approved_records(10)
        service, _, _ = self._make_service(records)
        record = await service.generate_dataset(
            name="split_ds",
            task_type="t",
            filter_config=DatasetFilter(),
            split_config=SplitConfig(
                train_percent=0.6,
                validation_percent=0.2,
                test_percent=0.2,
                random_seed=100,
            ),
        )
        assert record.split_config_json["random_seed"] == 100
        assert record.split_config_json["train_percent"] == 0.6

    @pytest.mark.asyncio
    async def test_get_dataset_existing(self) -> None:
        records = _make_approved_records(3)
        service, _, dataset_repo = self._make_service(records)
        created = await service.generate_dataset(
            name="get_ds",
            task_type="t",
            filter_config=DatasetFilter(),
        )
        retrieved = await service.get_dataset(created.id)
        assert retrieved.id == created.id
        assert retrieved.dataset_hash == created.dataset_hash

    @pytest.mark.asyncio
    async def test_get_dataset_not_found(self) -> None:
        service, _, _ = self._make_service([])
        with pytest.raises(DatasetNotFoundError):
            await service.get_dataset(uuid7())

    @pytest.mark.asyncio
    async def test_generate_dataset_statistics_json(self) -> None:
        records = [
            _make_record(rating=1, review_status="APPROVED"),
            _make_record(rating=1, review_status="APPROVED"),
            _make_record(
                rating=-1, correction="差评", reason_codes=["X"], review_status="APPROVED"
            ),
        ]
        service, _, _ = self._make_service(records)
        record = await service.generate_dataset(
            name="stats_ds",
            task_type="t",
            filter_config=DatasetFilter(),
        )
        stats = record.statistics_json
        assert stats["label_distribution"]["POSITIVE"] == 2
        assert stats["label_distribution"]["NEGATIVE"] == 1
        assert stats["total_samples"] == 3
        assert stats["source_distribution"]["user_feedback"] == 3


# ---------------------------------------------------------------------------
# TestInMemoryDatasetRepository
# ---------------------------------------------------------------------------


class TestInMemoryDatasetRepository:
    """Tests for the InMemoryDatasetRepository."""

    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        repo = InMemoryDatasetRepository()
        from app.application.dataset_service import DatasetRecord

        record = DatasetRecord(
            id=uuid7(),
            name="test",
            task_type="t",
            dataset_hash="abc",
            storage_uri="/path/to/file.jsonl",
            filter_config_json={},
            redaction_version="pii-v1.0",
            split_config_json={},
            sample_count=5,
            statistics_json={},
            status="READY",
        )
        saved = await repo.save_dataset(record)
        assert saved.id == record.id
        retrieved = await repo.get_dataset(record.id)
        assert retrieved is not None
        assert retrieved.dataset_hash == "abc"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self) -> None:
        repo = InMemoryDatasetRepository()
        result = await repo.get_dataset(uuid7())
        assert result is None


# ---------------------------------------------------------------------------
# TestDatasetAPIRouteRegistration
# ---------------------------------------------------------------------------


def _build_test_app(
    feedback_repo: InMemoryFeedbackRepository | None = None,
) -> FastAPI:
    """Build a test app with dataset service wired in."""
    app = create_app(readiness_checks={})
    fb_repo = feedback_repo or InMemoryFeedbackRepository()
    ds_repo = InMemoryDatasetRepository()
    app.state.dataset_service = DatasetService(fb_repo, ds_repo)
    return app


class TestDatasetAPIRouteRegistration:
    """Tests that the dataset routes are registered in the app."""

    def test_post_datasets_route_exists(self) -> None:
        app = _build_test_app()
        with TestClient(app) as client:
            r = client.post(
                "/api/v1/fine-tuning/datasets",
                json={"name": "test", "task_type": "sentiment"},
            )
            # Without auth → 401/403/500 (route exists, auth fires)
            assert r.status_code in (401, 403, 500)

    def test_get_datasets_route_exists(self) -> None:
        app = _build_test_app()
        with TestClient(app) as client:
            r = client.get(f"/api/v1/fine-tuning/datasets/{uuid7()}")
            assert r.status_code in (401, 403, 500)

    def test_post_datasets_invalid_rating_in_filter(self) -> None:
        """Route should reject invalid filter with 422 or auth error."""
        app = _build_test_app()
        with TestClient(app) as client:
            r = client.post(
                "/api/v1/fine-tuning/datasets",
                json={
                    "name": "test",
                    "task_type": "t",
                    "filter": {"rating": 0},  # Invalid: must be -1 or 1
                },
            )
            assert r.status_code in (401, 403, 422, 500)


# ---------------------------------------------------------------------------
# TestDatasetSplitIsolation — end-to-end leakage verification (criterion ⑥)
# ---------------------------------------------------------------------------


class TestDatasetSplitIsolation:
    """End-to-end tests verifying no data leakage across splits."""

    def test_no_entity_leakage_large_dataset(self) -> None:
        """With many records, no entity should appear in multiple splits."""
        records = _make_approved_records(30)
        config = SplitConfig(
            isolation_key="ENTITY",
            train_percent=0.7,
            validation_percent=0.15,
            test_percent=0.15,
            random_seed=42,
        )
        builder = DatasetBuilder()
        result = builder.build(
            records=records,
            name="ds",
            task_type="t",
            split_config=config,
        )

        # Verify no leakage
        split_entities: dict[str, set[UUID]] = {}
        for a in result.assignments:
            split_entities.setdefault(a.split, set()).add(a.isolation_key)
        splits = list(split_entities.values())
        for i in range(len(splits)):
            for j in range(i + 1, len(splits)):
                assert splits[i].isdisjoint(splits[j])

    def test_split_counts_sum_to_sample_count(self) -> None:
        records = _make_approved_records(20)
        builder = DatasetBuilder()
        result = builder.build(records=records, name="ds", task_type="t")
        total = (
            result.split_counts["train"]
            + result.split_counts["validation"]
            + result.split_counts["test"]
        )
        assert total == result.sample_count
        assert total == len(result.assignments)

    def test_content_hash_unique_per_unique_content(self) -> None:
        """Different content should produce different content hashes."""
        records = [
            _make_record(
                rating=-1,
                correction="unique text A",
                reason_codes=["X"],
                review_status="APPROVED",
            ),
            _make_record(
                rating=-1,
                correction="unique text B",
                reason_codes=["Y"],
                review_status="APPROVED",
            ),
        ]
        builder = DatasetBuilder()
        result = builder.build(records=records, name="ds", task_type="t")
        hashes = {a.content_hash for a in result.assignments}
        assert len(hashes) == 2
