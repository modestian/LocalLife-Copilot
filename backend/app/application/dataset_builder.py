"""Immutable JSONL dataset builder with stratified splitting and data card.

Implements the dataset generation pipeline defined in:
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §4.5:
  "dataset_hash 全局唯一；数据集发布后内容不可变"
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §11.8:
  datasets fields: dataset_hash, storage_uri, split_config_json,
  sample_count, statistics_json, quality_report_uri/hash
- docs/project/大众点评AI智能助手-05-具体设计.md §9.2:
  "按商家/时间分组切分 train/validation/test，避免同源泄漏"
  JSONL format: {"text":"...","label":"...","reason":"..."}
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.2:
  POST /api/v1/fine-tuning/datasets — 生成不可变 JSONL 数据集

ST-501 acceptance criteria:
- ⑤ JSONL 数据集生成后不可修改，保存 SHA-256、样本量、来源和质量报告
- ⑥ train/validation/test 按实体或会话隔离切分，无重复或数据泄漏
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.application.feedback import FeedbackRecord
from app.application.feedback_quality import (
    QualityReport,
    run_quality_pipeline,
)
from app.application.pii_redaction import RedactionService
from app.domain.feedback import SplitConfig

# ---------------------------------------------------------------------------
# Split assignment (which split a record belongs to)
# ---------------------------------------------------------------------------

SPLITS = ("train", "validation", "test")


@dataclass(frozen=True, slots=True)
class SplitAssignment:
    """A single record's split assignment.

    Attributes:
        record: The original feedback record (PII-redacted correction).
        split: One of 'train', 'validation', 'test'.
        content_json: The JSONL line content (text, label, reason).
        content_hash: SHA-256 of the content_json line.
        isolation_key: The conversation_id or entity_id used for grouping.
    """

    record: FeedbackRecord
    split: str
    content_json: dict[str, object]
    content_hash: str
    isolation_key: UUID


# ---------------------------------------------------------------------------
# Dataset build result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    """Output of the dataset generation pipeline.

    Contains all data needed to populate the ``datasets`` and
    ``dataset_items`` tables per §11.8.

    Attributes:
        dataset_hash: SHA-256 of the entire JSONL file content.
        sample_count: Total number of samples across all splits.
        split_counts: Mapping of split name → sample count.
        split_config: The SplitConfig used (for split_config_json).
        statistics: Label/source distribution dict (for statistics_json).
        data_card: Data card dict with metadata and statistics.
        assignments: Per-record split assignments with content and hash.
        storage_uri: Path where the JSONL file was written (or None).
        redaction_version: PII redaction rule version.
        quality_report: Quality report from the quality pipeline.
    """

    dataset_hash: str
    sample_count: int
    split_counts: dict[str, int]
    split_config: dict[str, object]
    statistics: dict[str, object]
    data_card: dict[str, object]
    assignments: list[SplitAssignment]
    storage_uri: str | None
    redaction_version: str
    quality_report: QualityReport


# ---------------------------------------------------------------------------
# Dataset splitter — entity-aware stratified split (criterion ⑥)
# ---------------------------------------------------------------------------


class DatasetSplitter:
    """Splits feedback records into train/validation/test by entity isolation.

    Per §9.2: "按商家/时间分组切分 train/validation/test，避免同源泄漏"
    Per criterion ⑥: "按实体或会话隔离切分，无重复或数据泄漏"

    Groups records by ``conversation_id`` (or a user-supplied entity key)
    and assigns entire groups to a single split, ensuring no entity
    appears in more than one split.
    """

    @staticmethod
    def _get_isolation_key(
        record: FeedbackRecord,
        isolation_key: str,
    ) -> UUID:
        """Extract the isolation key from a record.

        For CONVERSATION isolation, we use the message_id as a proxy since
        FeedbackRecord does not carry conversation_id directly.  In production,
        the repository will populate this via a join with messages.

        For ENTITY isolation, we use user_id as the entity proxy.
        """
        if isolation_key == "ENTITY":
            return record.user_id
        # CONVERSATION: use message_id as the conversation proxy.
        # In production, the repository join will provide conversation_id.
        return record.message_id

    @staticmethod
    def split(
        records: list[FeedbackRecord],
        config: SplitConfig,
    ) -> list[SplitAssignment]:
        """Split records into train/validation/test by entity isolation.

        Args:
            records: Accepted feedback records (post quality filter).
            config: Split configuration with percentages and seed.

        Returns:
            List of SplitAssignment, one per record.
        """
        if not records:
            return []

        # Group records by isolation key
        groups: dict[UUID, list[FeedbackRecord]] = {}
        for record in records:
            key = DatasetSplitter._get_isolation_key(record, config.isolation_key)
            groups.setdefault(key, []).append(record)

        # Shuffle group keys deterministically using random_seed
        group_keys = sorted(groups.keys())  # sort for determinism
        rng = random.Random(config.random_seed)
        rng.shuffle(group_keys)

        # Assign groups to splits by percentage
        total_groups = len(group_keys)
        train_end = int(total_groups * config.train_percent)
        val_end = train_end + int(total_groups * config.validation_percent)

        assignments: list[SplitAssignment] = []
        for idx, key in enumerate(group_keys):
            if idx < train_end:
                split = "train"
            elif idx < val_end:
                split = "validation"
            else:
                split = "test"

            for record in groups[key]:
                content = DatasetSplitter._build_content(record)
                content_str = json.dumps(content, sort_keys=True, ensure_ascii=False)
                content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

                assignments.append(
                    SplitAssignment(
                        record=record,
                        split=split,
                        content_json=content,
                        content_hash=content_hash,
                        isolation_key=key,
                    )
                )

        return assignments

    @staticmethod
    def _build_content(record: FeedbackRecord) -> dict[str, object]:
        """Build the JSONL line content from a feedback record.

        Per §9.2, the JSONL format is:
        {"text":"...", "label":"...", "reason":"..."}
        """
        text = record.correction or ""
        label = "POSITIVE" if record.rating == 1 else "NEGATIVE"
        reason = record.reason_codes[0] if record.reason_codes else ""
        return {"text": text, "label": label, "reason": reason}


# ---------------------------------------------------------------------------
# JSONL writer — writes immutable file and computes SHA-256 (criterion ⑤)
# ---------------------------------------------------------------------------


class JSONLWriter:
    """Writes split assignments to a JSONL file and computes the file hash.

    Per §4.5: "dataset_hash 全局唯一；数据集发布后内容不可变"
    Per §11.8: "storage_uri VARCHAR(1000) NOT NULL — JSONL 路径"

    The dataset_hash is the SHA-256 of the entire JSONL file content,
    computed by streaming all lines through the hash updater.
    """

    @staticmethod
    def write(
        assignments: list[SplitAssignment],
        output_path: str | Path,
    ) -> tuple[str, str]:
        """Write assignments to a JSONL file and return (hash, storage_uri).

        Args:
            assignments: Split assignments with content_json.
            output_path: File path for the JSONL output.

        Returns:
            Tuple of (dataset_hash, storage_uri) where dataset_hash is
            the SHA-256 hex digest of the file content.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        # Write lines in split order: train, validation, test
        # Within each split, preserve the original order from assignments.
        split_order = {"train": 0, "validation": 1, "test": 2}
        sorted_assignments = sorted(
            assignments,
            key=lambda a: (split_order.get(a.split, 99),),
        )

        # Use binary mode to ensure consistent \n line endings across
        # platforms (Windows text mode translates \n to \r\n, which
        # would cause hash mismatch between write-time and read-back).
        with path.open("wb") as f:
            for assignment in sorted_assignments:
                line = json.dumps(
                    assignment.content_json,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                line_bytes = (line + "\n").encode("utf-8")
                hasher.update(line_bytes)
                f.write(line_bytes)

        return hasher.hexdigest(), str(path.resolve())


# ---------------------------------------------------------------------------
# Data card generator — metadata, statistics, provenance (criterion ⑤)
# ---------------------------------------------------------------------------


class DataCardGenerator:
    """Generates a data card dict for the dataset.

    Per §9.2: "保存 dataset_hash、标签分布、许可、脱敏报告和固定 seed"
    Per §11.8: statistics_json = "标签/来源分布"

    The data card includes:
    - Dataset metadata (name, task_type, hash, sample_count)
    - Split distribution (train/validation/test counts)
    - Label distribution (POSITIVE/NEGATIVE counts)
    - Source distribution
    - Redaction version and PII findings
    - Quality report summary
    - Generation timestamp and configuration
    """

    @staticmethod
    def generate(
        *,
        name: str,
        task_type: str,
        dataset_hash: str,
        sample_count: int,
        split_counts: dict[str, int],
        label_distribution: dict[str, int],
        source_distribution: dict[str, int],
        redaction_version: str,
        quality_report: QualityReport,
        split_config: SplitConfig,
        generated_at: datetime | None = None,
    ) -> dict[str, object]:
        """Build the data card dictionary."""
        ts = generated_at or datetime.now(tz=UTC)
        return {
            "name": name,
            "task_type": task_type,
            "dataset_hash": dataset_hash,
            "sample_count": sample_count,
            "generated_at": ts.isoformat(),
            "splits": {
                "train": split_counts.get("train", 0),
                "validation": split_counts.get("validation", 0),
                "test": split_counts.get("test", 0),
            },
            "label_distribution": dict(label_distribution),
            "source_distribution": dict(source_distribution),
            "redaction": {
                "version": redaction_version,
                "pii_findings": dict(quality_report.pii_findings),
            },
            "quality": {
                "total_candidates": quality_report.total_candidates,
                "total_accepted": quality_report.total_accepted,
                "total_rejected": quality_report.total_rejected,
                "acceptance_rate": quality_report.acceptance_rate,
                "rejection_reasons": dict(quality_report.rejection_reasons),
            },
            "split_config": {
                "isolation_key": split_config.isolation_key,
                "train_percent": split_config.train_percent,
                "validation_percent": split_config.validation_percent,
                "test_percent": split_config.test_percent,
                "random_seed": split_config.random_seed,
            },
        }


# ---------------------------------------------------------------------------
# Dataset builder — orchestrates the full pipeline
# ---------------------------------------------------------------------------


class DatasetBuilder:
    """Orchestrates the full dataset generation pipeline.

    Pipeline steps (per §9.2 and acceptance criteria ⑤⑥):
    1. PII redaction on correction fields
    2. Quality pipeline: source check → quality filter → quality report
    3. Entity-aware stratified split (no leakage)
    4. JSONL file writing with SHA-256 hash
    5. Data card generation with statistics and provenance

    Usage:
        builder = DatasetBuilder()
        result = builder.build(
            records=feedback_records,
            name="sentiment_v1",
            task_type="sentiment_classification",
            split_config=SplitConfig(...),
        )
    """

    def __init__(self, redaction_service: RedactionService | None = None) -> None:
        self._redaction = redaction_service or RedactionService()

    def build(
        self,
        *,
        records: list[FeedbackRecord],
        name: str,
        task_type: str,
        split_config: SplitConfig | None = None,
        output_path: str | Path | None = None,
    ) -> DatasetBuildResult:
        """Run the full pipeline and return a DatasetBuildResult.

        Args:
            records: Raw feedback records (will be redacted and filtered).
            name: Dataset name (for datasets.name).
            task_type: Training task type (for datasets.task_type).
            split_config: Split configuration or None for defaults.
            output_path: Path to write JSONL file, or None to skip writing.

        Returns:
            DatasetBuildResult with hash, counts, data card and assignments.
        """
        config = split_config or SplitConfig()

        # Step 1: PII redaction on correction fields
        redacted_records, pii_findings = self._redact_batch(records)

        # Step 2: Quality pipeline (source + quality + report)
        label_dist = self._compute_label_distribution(redacted_records)
        source_dist = {"user_feedback": len(redacted_records)}
        quality_result, quality_report = run_quality_pipeline(
            redacted_records,
            pii_findings=pii_findings,
            label_distribution=label_dist,
            source_distribution=source_dist,
        )

        # Step 3: Entity-aware stratified split
        assignments = DatasetSplitter.split(quality_result.accepted, config)

        # Step 4: Write JSONL and compute hash (or compute hash in-memory)
        if output_path is not None:
            dataset_hash, storage_uri = JSONLWriter.write(assignments, output_path)
        else:
            dataset_hash, storage_uri = self._compute_hash_only(assignments)

        # Step 5: Build statistics and data card
        split_counts = self._count_splits(assignments)
        final_label_dist = self._compute_label_distribution(quality_result.accepted)
        final_source_dist = {"user_feedback": len(quality_result.accepted)}

        statistics: dict[str, object] = {
            "total_samples": len(assignments),
            "train_samples": split_counts.get("train", 0),
            "validation_samples": split_counts.get("validation", 0),
            "test_samples": split_counts.get("test", 0),
            "label_distribution": dict(final_label_dist),
            "source_distribution": dict(final_source_dist),
        }

        data_card = DataCardGenerator.generate(
            name=name,
            task_type=task_type,
            dataset_hash=dataset_hash,
            sample_count=len(assignments),
            split_counts=split_counts,
            label_distribution=final_label_dist,
            source_distribution=final_source_dist,
            redaction_version=self._redaction.version,
            quality_report=quality_report,
            split_config=config,
        )

        split_config_dict: dict[str, object] = {
            "isolation_key": config.isolation_key,
            "train_percent": config.train_percent,
            "validation_percent": config.validation_percent,
            "test_percent": config.test_percent,
            "random_seed": config.random_seed,
        }

        return DatasetBuildResult(
            dataset_hash=dataset_hash,
            sample_count=len(assignments),
            split_counts=split_counts,
            split_config=split_config_dict,
            statistics=statistics,
            data_card=data_card,
            assignments=assignments,
            storage_uri=storage_uri,
            redaction_version=self._redaction.version,
            quality_report=quality_report,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _redact_batch(
        self, records: list[FeedbackRecord]
    ) -> tuple[list[FeedbackRecord], dict[str, int]]:
        """Apply PII redaction to correction fields.

        Returns a new list of records with redacted correction text and
        the aggregated PII findings dict.
        """
        if not records:
            return [], {}

        redacted_records: list[FeedbackRecord] = []
        pii_findings: dict[str, int] = {}

        for record in records:
            if record.correction:
                scan = self._redaction.redact(record.correction)
                for k, v in scan.findings.items():
                    pii_findings[k] = pii_findings.get(k, 0) + v
                # Create a new record with redacted correction
                redacted_records.append(
                    FeedbackRecord(
                        id=record.id,
                        user_id=record.user_id,
                        message_id=record.message_id,
                        rating=record.rating,
                        correction=scan.redacted_text,
                        reason_codes=record.reason_codes,
                        pii_flagged=scan.pii_detected,
                        review_status=record.review_status,
                        version=record.version,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
            else:
                redacted_records.append(record)

        return redacted_records, pii_findings

    @staticmethod
    def _compute_label_distribution(
        records: list[FeedbackRecord],
    ) -> dict[str, int]:
        """Compute POSITIVE/NEGATIVE label distribution."""
        dist: dict[str, int] = {"POSITIVE": 0, "NEGATIVE": 0}
        for record in records:
            label = "POSITIVE" if record.rating == 1 else "NEGATIVE"
            dist[label] = dist.get(label, 0) + 1
        return dist

    @staticmethod
    def _count_splits(assignments: list[SplitAssignment]) -> dict[str, int]:
        """Count samples per split."""
        counts: dict[str, int] = {"train": 0, "validation": 0, "test": 0}
        for a in assignments:
            counts[a.split] = counts.get(a.split, 0) + 1
        return counts

    @staticmethod
    def _compute_hash_only(assignments: list[SplitAssignment]) -> tuple[str, None]:
        """Compute SHA-256 of JSONL content without writing to disk.

        Used when output_path is None (e.g., in tests or preview mode).
        """
        hasher = hashlib.sha256()
        split_order = {"train": 0, "validation": 1, "test": 2}
        sorted_assignments = sorted(
            assignments,
            key=lambda a: (split_order.get(a.split, 99),),
        )
        for assignment in sorted_assignments:
            line = json.dumps(
                assignment.content_json,
                sort_keys=True,
                ensure_ascii=False,
            )
            hasher.update((line + "\n").encode("utf-8"))
        return hasher.hexdigest(), None
