"""Source authorization checking and quality filtering for dataset generation.

Implements the rules defined in:
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §4.4:
  "correction 最大 4000 字，入库前执行敏感信息检测和脱敏标记"
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §9:
  "训练数据集不直接引用可变业务表，生成时固化、脱敏、哈希并记录来源许可"
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §11.8:
  datasets.statistics_json = "标签/来源分布"
- docs/project/大众点评AI智能助手-05-具体设计.md §9.2:
  "去除重复和近重复文本；脱敏手机号、地址细节、账号标识"

ST-501 acceptance criteria:
- ④ 未授权样本不得进入数据集
- ⑤ 保存样本量、来源和质量报告
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.application.feedback import FeedbackRecord

# ---------------------------------------------------------------------------
# Minimum content length for a feedback to be considered valid
# ---------------------------------------------------------------------------

MIN_CONTENT_LENGTH = 2

# Valid review statuses for dataset inclusion
# Per §4.4: only APPROVED feedback may enter dataset
AUTHORIZED_REVIEW_STATUS = "APPROVED"


# ---------------------------------------------------------------------------
# Quality check result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityCheckResult:
    """Result of source authorization and quality filtering.

    Attributes:
        total_candidates: Total number of feedback records evaluated.
        accepted: Records that passed all checks and are eligible
            for dataset inclusion.
        rejected: Tuples of (record, reason) for rejected entries.
        acceptance_rate: Fraction of candidates accepted (0.0–1.0).
        rejection_reasons: Mapping of rejection reason → count.
    """

    total_candidates: int
    accepted: list[FeedbackRecord] = field(default_factory=list)
    rejected: list[tuple[FeedbackRecord, str]] = field(default_factory=list)
    acceptance_rate: float = 0.0
    rejection_reasons: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source authorization checker
# ---------------------------------------------------------------------------


class SourceChecker:
    """Verifies that feedback is authorized for dataset inclusion.

    Per §9: "记录来源许可" — only feedback with ``review_status ==
    'APPROVED'`` may enter a training dataset.

    Per criterion ④: "未授权样本不得进入数据集".
    """

    @staticmethod
    def is_authorized(record: FeedbackRecord) -> bool:
        """Return True if the feedback has been approved for dataset use."""
        return record.review_status == AUTHORIZED_REVIEW_STATUS

    @staticmethod
    def check_batch(
        records: list[FeedbackRecord],
    ) -> tuple[list[FeedbackRecord], list[tuple[FeedbackRecord, str]]]:
        """Split records into (authorized, rejected) lists.

        Rejected entries include the rejection reason.
        """
        authorized: list[FeedbackRecord] = []
        rejected: list[tuple[FeedbackRecord, str]] = []
        for record in records:
            if SourceChecker.is_authorized(record):
                authorized.append(record)
            else:
                rejected.append((record, f"source_unauthorized:{record.review_status}"))
        return authorized, rejected


# ---------------------------------------------------------------------------
# Quality filter (low-quality removal)
# ---------------------------------------------------------------------------


class QualityFilter:
    """Removes low-quality feedback entries from the candidate pool.

    Per §9.2: "去除重复和近重复文本"
    Per §4.4: negative feedback requires reason_codes or correction

    Rules:
    1. Negative feedback (rating=-1) with no correction AND no reason_codes → reject
    2. Correction text shorter than MIN_CONTENT_LENGTH → reject
    3. Duplicate correction text (exact match after normalization) → reject
    """

    @staticmethod
    def _has_content(record: FeedbackRecord) -> bool:
        """Check if a negative feedback has meaningful content.

        Per §4.4: thumbs-down requires at least one reason_code or correction.
        """
        if record.rating != -1:
            return True
        return bool(record.reason_codes) or bool(record.correction)

    @staticmethod
    def _has_min_length(record: FeedbackRecord) -> bool:
        """Check if the correction text (if any) meets minimum length.

        Positive feedback without correction is still valid (thumbs-up needs
        no explanation).  Only corrections that exist but are too short
        are rejected.
        """
        if record.correction is None:
            return True
        return len(record.correction.strip()) >= MIN_CONTENT_LENGTH

    @staticmethod
    def _normalize_text(text: str | None) -> str:
        """Normalize text for duplicate detection (strip + lowercase)."""
        if text is None:
            return ""
        return text.strip().lower()

    @staticmethod
    def filter(
        records: list[FeedbackRecord],
    ) -> tuple[list[FeedbackRecord], list[tuple[FeedbackRecord, str]]]:
        """Filter out low-quality entries.

        Returns (accepted, rejected) where rejected contains (record, reason).
        """
        accepted: list[FeedbackRecord] = []
        rejected: list[tuple[FeedbackRecord, str]] = []
        seen_texts: set[str] = set()

        for record in records:
            # Rule 1: negative feedback must have content
            if not QualityFilter._has_content(record):
                rejected.append((record, "negative_feedback_no_content"))
                continue

            # Rule 2: correction must meet minimum length
            if not QualityFilter._has_min_length(record):
                rejected.append((record, "correction_too_short"))
                continue

            # Rule 3: deduplicate by normalized correction text
            # Only deduplicate when there is a correction; feedback without
            # correction (pure thumbs-up) is not subject to text dedup.
            if record.correction is not None:
                normalized = QualityFilter._normalize_text(record.correction)
                if normalized in seen_texts:
                    rejected.append((record, "duplicate_text"))
                    continue
                seen_texts.add(normalized)

            accepted.append(record)

        return accepted, rejected


# ---------------------------------------------------------------------------
# Quality report generator
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Aggregated quality report for a dataset generation run.

    This is serialized into ``datasets.statistics_json`` and referenced by
    ``datasets.quality_report_uri`` / ``quality_report_hash`` per §11.8.
    """

    total_candidates: int
    total_accepted: int
    total_rejected: int
    acceptance_rate: float
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    pii_findings: dict[str, int] = field(default_factory=dict)
    label_distribution: dict[str, int] = field(default_factory=dict)
    source_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-compatible dict for datasets.statistics_json."""
        return {
            "total_candidates": self.total_candidates,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "acceptance_rate": self.acceptance_rate,
            "rejection_reasons": dict(self.rejection_reasons),
            "pii_findings": dict(self.pii_findings),
            "label_distribution": dict(self.label_distribution),
            "source_distribution": dict(self.source_distribution),
        }


def build_quality_report(
    result: QualityCheckResult,
    *,
    pii_findings: dict[str, int] | None = None,
    label_distribution: dict[str, int] | None = None,
    source_distribution: dict[str, int] | None = None,
) -> QualityReport:
    """Build a :class:`QualityReport` from a :class:`QualityCheckResult`.

    Args:
        result: The quality check result from the filter pipeline.
        pii_findings: Aggregated PII detection counts (from RedactionService).
        label_distribution: Mapping of label → count in the accepted set.
        source_distribution: Mapping of source type → count.
    """
    total = result.total_candidates
    accepted = len(result.accepted)
    rejected = len(result.rejected)
    rate = accepted / total if total > 0 else 0.0

    return QualityReport(
        total_candidates=total,
        total_accepted=accepted,
        total_rejected=rejected,
        acceptance_rate=rate,
        rejection_reasons=dict(result.rejection_reasons),
        pii_findings=pii_findings or {},
        label_distribution=label_distribution or {},
        source_distribution=source_distribution or {},
    )


# ---------------------------------------------------------------------------
# Pipeline: SourceChecker → QualityFilter → QualityReport
# ---------------------------------------------------------------------------


def run_quality_pipeline(
    records: list[FeedbackRecord],
    *,
    pii_findings: dict[str, int] | None = None,
    label_distribution: dict[str, int] | None = None,
    source_distribution: dict[str, int] | None = None,
) -> tuple[QualityCheckResult, QualityReport]:
    """Run the full quality pipeline: source check → quality filter → report.

    This is the main entry point for dataset generation (TK-501-03).
    The pipeline applies checks in order:

    1. SourceChecker: reject unauthorized (non-APPROVED) feedback
    2. QualityFilter: reject low-quality entries (no content, too short, duplicate)
    3. QualityReport: aggregate statistics for datasets.statistics_json

    Returns (QualityCheckResult, QualityReport).
    """
    total = len(records)

    # Step 1: Source authorization
    authorized, source_rejected = SourceChecker.check_batch(records)

    # Step 2: Quality filtering on authorized records
    quality_accepted, quality_rejected = QualityFilter.filter(authorized)

    # Combine rejections
    all_rejected = source_rejected + quality_rejected

    # Build rejection reason summary
    rejection_reasons: dict[str, int] = {}
    for _record, reason in all_rejected:
        rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    result = QualityCheckResult(
        total_candidates=total,
        accepted=quality_accepted,
        rejected=all_rejected,
        acceptance_rate=len(quality_accepted) / total if total > 0 else 0.0,
        rejection_reasons=rejection_reasons,
    )

    report = build_quality_report(
        result,
        pii_findings=pii_findings,
        label_distribution=label_distribution,
        source_distribution=source_distribution,
    )

    return result, report
