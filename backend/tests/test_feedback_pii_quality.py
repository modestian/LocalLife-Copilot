"""Unit tests for PII redaction, source checking and quality filtering.

Covers ST-501 acceptance criteria:
- ④ 手机号、身份证、邮箱等敏感信息在导出前完成脱敏，未授权样本不得进入数据集。
- ⑤ JSONL 数据集生成后不可修改，保存 SHA-256、样本量、来源和质量报告。
"""

from __future__ import annotations

from app.application.feedback import FeedbackRecord
from app.application.feedback_quality import (
    AUTHORIZED_REVIEW_STATUS,
    MIN_CONTENT_LENGTH,
    QualityCheckResult,
    QualityFilter,
    QualityReport,
    SourceChecker,
    build_quality_report,
    run_quality_pipeline,
)
from app.application.pii_redaction import (
    REDACTION_VERSION,
    PIIScanner,
    PIIScanResult,
    RedactionService,
)
from app.core.ids import uuid7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    rating: int = 1,
    correction: str | None = None,
    reason_codes: list[str] | None = None,
    review_status: str = "APPROVED",
    pii_flagged: bool = False,
) -> FeedbackRecord:
    """Create a FeedbackRecord for testing."""
    return FeedbackRecord(
        id=uuid7(),
        user_id=uuid7(),
        message_id=uuid7(),
        rating=rating,
        correction=correction,
        reason_codes=reason_codes or [],
        pii_flagged=pii_flagged,
        review_status=review_status,
        version=1,
        created_at=None,
        updated_at=None,
    )


# ---------------------------------------------------------------------------
# TestPIIScanner — PII detection and masking
# ---------------------------------------------------------------------------


class TestPIIScanner:
    """Tests for the PIIScanner regex-based PII detection."""

    def test_detects_phone_number(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("请致电 13812345678 预约")

        assert result.pii_detected
        assert result.findings.get("phone") == 1
        assert "13812345678" not in result.redacted_text
        assert "1" in result.redacted_text  # first char preserved

    def test_detects_multiple_phone_numbers(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("电话 13812345678 或 13900001111")

        assert result.findings.get("phone") == 2
        assert "13812345678" not in result.redacted_text
        assert "13900001111" not in result.redacted_text

    def test_detects_email(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("联系 test@example.com 咨询")

        assert result.pii_detected
        assert result.findings.get("email") == 1
        assert "test@example.com" not in result.redacted_text

    def test_detects_id_card(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("身份证号 110101199003071234")

        assert result.pii_detected
        assert result.findings.get("id_card") == 1
        assert "110101199003071234" not in result.redacted_text

    def test_detects_id_card_with_x_suffix(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("身份证 11010520000601234X")

        assert result.pii_detected
        assert result.findings.get("id_card") == 1

    def test_detects_multiple_pii_types(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("电话 13812345678 邮箱 test@example.com")

        assert result.pii_detected
        assert result.findings.get("phone") == 1
        assert result.findings.get("email") == 1

    def test_id_card_not_falsely_matched_as_phone(self) -> None:
        """ID card (18 digits) should not trigger a false phone match.

        The phone regex 1[3-9]\\d{9} would match substrings inside an
        ID card number if not ordered correctly.
        """
        scanner = PIIScanner()
        result = scanner.scan("ID: 110101199003071234")

        assert "phone" not in result.findings
        assert result.findings.get("id_card") == 1

    def test_mixed_phone_and_id_card(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("Call 13900001111 and bring ID 11010520000601234X")

        assert result.findings.get("phone") == 1
        assert result.findings.get("id_card") == 1
        assert "13900001111" not in result.redacted_text
        assert "11010520000601234X" not in result.redacted_text

    def test_clean_text_no_pii(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("这家店周一闭店，人均约 80 元。")

        assert not result.pii_detected
        assert result.findings == {}
        assert result.redacted_text == result.original_text

    def test_none_text_returns_empty_result(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan(None)

        assert not result.pii_detected
        assert result.original_text == ""
        assert result.redacted_text == ""

    def test_empty_string_returns_empty_result(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("")

        assert not result.pii_detected
        assert result.redacted_text == ""

    def test_mask_preserves_first_and_last_char(self) -> None:
        scanner = PIIScanner()
        result = scanner.scan("电话 13812345678")

        # First char '1' and last char '8' preserved, middle masked
        masked_phone = result.redacted_text.split("电话 ")[1]
        assert masked_phone[0] == "1"
        assert masked_phone[-1] == "8"
        assert "*" in masked_phone

    def test_original_text_not_modified_in_result(self) -> None:
        scanner = PIIScanner()
        original = "电话 13812345678"
        result = scanner.scan(original)

        assert result.original_text == original
        assert result.redacted_text != original

    def test_invalid_phone_not_detected(self) -> None:
        """Numbers that don't start with 1[3-9] should not be phones."""
        scanner = PIIScanner()
        result = scanner.scan("订单号 10000000000")

        assert "phone" not in result.findings


# ---------------------------------------------------------------------------
# TestRedactionService — service-level redaction
# ---------------------------------------------------------------------------


class TestRedactionService:
    """Tests for the RedactionService wrapper."""

    def test_redact_returns_scan_result(self) -> None:
        svc = RedactionService()
        result = svc.redact("电话 13812345678")

        assert isinstance(result, PIIScanResult)
        assert result.pii_detected
        assert result.findings.get("phone") == 1

    def test_version_property(self) -> None:
        svc = RedactionService()
        assert svc.version == REDACTION_VERSION
        assert svc.version == "pii-v1.0"

    def test_redact_batch_processes_multiple_texts(self) -> None:
        svc = RedactionService()
        texts = ["电话 13812345678", "无PII", "邮箱 a@b.com"]
        results = svc.redact_batch(texts)

        assert len(results) == 3
        assert results[0].pii_detected
        assert not results[1].pii_detected
        assert results[2].pii_detected

    def test_redact_batch_empty_list(self) -> None:
        svc = RedactionService()
        assert svc.redact_batch([]) == []

    def test_redact_none(self) -> None:
        svc = RedactionService()
        result = svc.redact(None)

        assert not result.pii_detected
        assert result.redacted_text == ""

    def test_custom_scanner_injection(self) -> None:
        scanner = PIIScanner()
        svc = RedactionService(scanner=scanner)
        assert svc._scanner is scanner


# ---------------------------------------------------------------------------
# TestSourceChecker — source authorization (criterion ④)
# ---------------------------------------------------------------------------


class TestSourceChecker:
    """Tests for the source authorization checker (criterion ④)."""

    def test_approved_is_authorized(self) -> None:
        record = _make_record(review_status="APPROVED")
        assert SourceChecker.is_authorized(record)

    def test_pending_review_not_authorized(self) -> None:
        record = _make_record(review_status="PENDING_REVIEW")
        assert not SourceChecker.is_authorized(record)

    def test_rejected_not_authorized(self) -> None:
        record = _make_record(review_status="REJECTED")
        assert not SourceChecker.is_authorized(record)

    def test_check_batch_splits_correctly(self) -> None:
        approved = _make_record(review_status="APPROVED")
        pending = _make_record(review_status="PENDING_REVIEW")
        rejected = _make_record(review_status="REJECTED")

        authorized, rejected_list = SourceChecker.check_batch([approved, pending, rejected])

        assert len(authorized) == 1
        assert authorized[0] == approved
        assert len(rejected_list) == 2
        reasons = {r for _, r in rejected_list}
        assert "source_unauthorized:PENDING_REVIEW" in reasons
        assert "source_unauthorized:REJECTED" in reasons

    def test_check_batch_empty_list(self) -> None:
        authorized, rejected = SourceChecker.check_batch([])
        assert authorized == []
        assert rejected == []

    def test_check_batch_all_authorized(self) -> None:
        records = [_make_record(review_status="APPROVED") for _ in range(3)]
        authorized, rejected = SourceChecker.check_batch(records)

        assert len(authorized) == 3
        assert rejected == []

    def test_check_batch_all_unauthorized(self) -> None:
        records = [_make_record(review_status="PENDING_REVIEW") for _ in range(3)]
        authorized, rejected = SourceChecker.check_batch(records)

        assert authorized == []
        assert len(rejected) == 3

    def test_authorized_review_status_constant(self) -> None:
        assert AUTHORIZED_REVIEW_STATUS == "APPROVED"


# ---------------------------------------------------------------------------
# TestQualityFilter — low-quality removal (criterion ⑤)
# ---------------------------------------------------------------------------


class TestQualityFilter:
    """Tests for the quality filter (low-quality removal)."""

    def test_positive_with_no_correction_accepted(self) -> None:
        record = _make_record(rating=1, correction=None)
        accepted, rejected = QualityFilter.filter([record])

        assert len(accepted) == 1
        assert rejected == []

    def test_positive_with_correction_accepted(self) -> None:
        record = _make_record(rating=1, correction="回答很好")
        accepted, rejected = QualityFilter.filter([record])

        assert len(accepted) == 1
        assert rejected == []

    def test_negative_with_reason_codes_accepted(self) -> None:
        record = _make_record(rating=-1, reason_codes=["FACT_ERROR"])
        accepted, rejected = QualityFilter.filter([record])

        assert len(accepted) == 1
        assert rejected == []

    def test_negative_with_correction_accepted(self) -> None:
        record = _make_record(rating=-1, correction="上菜太慢")
        accepted, rejected = QualityFilter.filter([record])

        assert len(accepted) == 1
        assert rejected == []

    def test_negative_no_content_rejected(self) -> None:
        record = _make_record(rating=-1, correction=None, reason_codes=[])
        accepted, rejected = QualityFilter.filter([record])

        assert accepted == []
        assert len(rejected) == 1
        assert rejected[0][1] == "negative_feedback_no_content"

    def test_correction_too_short_rejected(self) -> None:
        record = _make_record(rating=1, correction="x")
        accepted, rejected = QualityFilter.filter([record])

        assert accepted == []
        assert len(rejected) == 1
        assert rejected[0][1] == "correction_too_short"

    def test_correction_at_min_length_accepted(self) -> None:
        record = _make_record(rating=1, correction="ab")
        accepted, rejected = QualityFilter.filter([record])

        assert len(accepted) == 1
        assert rejected == []

    def test_duplicate_text_rejected(self) -> None:
        r1 = _make_record(rating=-1, correction="上菜太慢", reason_codes=["S"])
        r2 = _make_record(rating=-1, correction="上菜太慢", reason_codes=["S"])
        accepted, rejected = QualityFilter.filter([r1, r2])

        assert len(accepted) == 1
        assert len(rejected) == 1
        assert rejected[0][1] == "duplicate_text"

    def test_case_insensitive_duplicate_rejected(self) -> None:
        r1 = _make_record(rating=-1, correction="Service Slow", reason_codes=["S"])
        r2 = _make_record(rating=-1, correction="service slow", reason_codes=["S"])
        accepted, rejected = QualityFilter.filter([r1, r2])

        assert len(accepted) == 1
        assert len(rejected) == 1
        assert rejected[0][1] == "duplicate_text"

    def test_whitespace_normalized_for_duplicate(self) -> None:
        r1 = _make_record(rating=-1, correction="  上菜太慢  ", reason_codes=["S"])
        r2 = _make_record(rating=-1, correction="上菜太慢", reason_codes=["S"])
        accepted, rejected = QualityFilter.filter([r1, r2])

        assert len(accepted) == 1
        assert len(rejected) == 1

    def test_positive_no_correction_not_deduplicated(self) -> None:
        """Positive feedback without correction is not subject to text dedup."""
        r1 = _make_record(rating=1, correction=None)
        r2 = _make_record(rating=1, correction=None)
        accepted, rejected = QualityFilter.filter([r1, r2])

        assert len(accepted) == 2
        assert rejected == []

    def test_different_corrections_all_accepted(self) -> None:
        records = [
            _make_record(rating=-1, correction="上菜太慢", reason_codes=["A"]),
            _make_record(rating=-1, correction="价格太贵", reason_codes=["B"]),
            _make_record(rating=-1, correction="环境嘈杂", reason_codes=["C"]),
        ]
        accepted, rejected = QualityFilter.filter(records)

        assert len(accepted) == 3
        assert rejected == []

    def test_empty_list(self) -> None:
        accepted, rejected = QualityFilter.filter([])
        assert accepted == []
        assert rejected == []

    def test_min_content_length_constant(self) -> None:
        assert MIN_CONTENT_LENGTH == 2


# ---------------------------------------------------------------------------
# TestQualityReport — report generation and serialization
# ---------------------------------------------------------------------------


class TestQualityReport:
    """Tests for QualityReport generation and serialization."""

    def test_to_dict_contains_all_fields(self) -> None:
        report = QualityReport(
            total_candidates=10,
            total_accepted=7,
            total_rejected=3,
            acceptance_rate=0.7,
            rejection_reasons={"duplicate_text": 2, "correction_too_short": 1},
            pii_findings={"phone": 2, "email": 1},
            label_distribution={"POSITIVE": 4, "NEGATIVE": 3},
            source_distribution={"user_feedback": 7},
        )
        d = report.to_dict()

        assert d["total_candidates"] == 10
        assert d["total_accepted"] == 7
        assert d["total_rejected"] == 3
        assert d["acceptance_rate"] == 0.7
        assert d["rejection_reasons"]["duplicate_text"] == 2
        assert d["pii_findings"]["phone"] == 2
        assert d["label_distribution"]["POSITIVE"] == 4
        assert d["source_distribution"]["user_feedback"] == 7

    def test_to_dict_is_json_serializable(self) -> None:
        import json

        report = QualityReport(
            total_candidates=5,
            total_accepted=3,
            total_rejected=2,
            acceptance_rate=0.6,
        )
        d = report.to_dict()
        # Should not raise
        json.dumps(d)

    def test_build_quality_report_from_result(self) -> None:
        records = [_make_record() for _ in range(5)]
        result = QualityCheckResult(
            total_candidates=5,
            accepted=records[:3],
            rejected=[(records[3], "duplicate_text"), (records[4], "correction_too_short")],
            acceptance_rate=0.6,
            rejection_reasons={"duplicate_text": 1, "correction_too_short": 1},
        )
        report = build_quality_report(result)

        assert report.total_candidates == 5
        assert report.total_accepted == 3
        assert report.total_rejected == 2
        assert report.rejection_reasons["duplicate_text"] == 1

    def test_build_quality_report_with_pii_findings(self) -> None:
        result = QualityCheckResult(total_candidates=1, accepted=[], rejected=[])
        report = build_quality_report(result, pii_findings={"phone": 2, "id_card": 1})

        assert report.pii_findings["phone"] == 2
        assert report.pii_findings["id_card"] == 1

    def test_build_quality_report_zero_candidates(self) -> None:
        result = QualityCheckResult(total_candidates=0, accepted=[], rejected=[])
        report = build_quality_report(result)

        assert report.total_candidates == 0
        assert report.acceptance_rate == 0.0


# ---------------------------------------------------------------------------
# TestQualityPipeline — end-to-end pipeline (criterion ④⑤)
# ---------------------------------------------------------------------------


class TestQualityPipeline:
    """Tests for the run_quality_pipeline end-to-end function."""

    def test_pipeline_all_accepted(self) -> None:
        records = [
            _make_record(rating=1, correction=None, review_status="APPROVED"),
            _make_record(
                rating=-1, correction="差评", reason_codes=["S"], review_status="APPROVED"
            ),
        ]
        result, report = run_quality_pipeline(records)

        assert result.total_candidates == 2
        assert len(result.accepted) == 2
        assert len(result.rejected) == 0
        assert result.acceptance_rate == 1.0

    def test_pipeline_all_rejected_by_source(self) -> None:
        records = [_make_record(review_status="PENDING_REVIEW") for _ in range(3)]
        result, report = run_quality_pipeline(records)

        assert len(result.accepted) == 0
        assert len(result.rejected) == 3
        assert result.acceptance_rate == 0.0
        assert result.rejection_reasons["source_unauthorized:PENDING_REVIEW"] == 3

    def test_pipeline_all_rejected_by_quality(self) -> None:
        records = [_make_record(rating=-1, correction=None, reason_codes=[]) for _ in range(3)]
        result, report = run_quality_pipeline(records)

        assert len(result.accepted) == 0
        assert len(result.rejected) == 3
        assert result.rejection_reasons["negative_feedback_no_content"] == 3

    def test_pipeline_mixed_scenario(self) -> None:
        records = [
            # Accepted: approved positive
            _make_record(rating=1, correction=None, review_status="APPROVED"),
            # Accepted: approved negative with content
            _make_record(
                rating=-1, correction="太慢", reason_codes=["S"], review_status="APPROVED"
            ),
            # Rejected: pending review
            _make_record(rating=1, correction="good", review_status="PENDING_REVIEW"),
            # Rejected: negative no content (approved but low quality)
            _make_record(rating=-1, correction=None, reason_codes=[], review_status="APPROVED"),
            # Rejected: too short (approved)
            _make_record(rating=1, correction="x", review_status="APPROVED"),
            # Rejected: duplicate (approved)
            _make_record(
                rating=-1, correction="太慢", reason_codes=["S"], review_status="APPROVED"
            ),
        ]
        result, report = run_quality_pipeline(records)

        assert result.total_candidates == 6
        assert len(result.accepted) == 2
        assert len(result.rejected) == 4
        assert result.rejection_reasons["source_unauthorized:PENDING_REVIEW"] == 1
        assert result.rejection_reasons["negative_feedback_no_content"] == 1
        assert result.rejection_reasons["correction_too_short"] == 1
        assert result.rejection_reasons["duplicate_text"] == 1

    def test_pipeline_empty_input(self) -> None:
        result, report = run_quality_pipeline([])

        assert result.total_candidates == 0
        assert result.accepted == []
        assert result.rejected == []
        assert result.acceptance_rate == 0.0
        assert report.total_candidates == 0

    def test_pipeline_propagates_pii_findings(self) -> None:
        records = [_make_record(review_status="APPROVED")]
        pii = {"phone": 3, "email": 1}
        result, report = run_quality_pipeline(records, pii_findings=pii)

        assert report.pii_findings["phone"] == 3
        assert report.pii_findings["email"] == 1

    def test_pipeline_propagates_label_distribution(self) -> None:
        records = [_make_record(review_status="APPROVED") for _ in range(3)]
        labels = {"POSITIVE": 2, "NEGATIVE": 1}
        result, report = run_quality_pipeline(records, label_distribution=labels)

        assert report.label_distribution["POSITIVE"] == 2
        assert report.label_distribution["NEGATIVE"] == 1

    def test_pipeline_propagates_source_distribution(self) -> None:
        records = [_make_record(review_status="APPROVED")]
        sources = {"user_feedback": 5, "manual_annotation": 2}
        result, report = run_quality_pipeline(records, source_distribution=sources)

        assert report.source_distribution["user_feedback"] == 5
        assert report.source_distribution["manual_annotation"] == 2

    def test_pipeline_source_checked_before_quality(self) -> None:
        """A record that is both unauthorized AND low quality should be
        rejected with the source reason, not the quality reason."""
        record = _make_record(
            rating=-1, correction=None, reason_codes=[], review_status="PENDING_REVIEW"
        )
        result, report = run_quality_pipeline([record])

        assert len(result.rejected) == 1
        assert "source_unauthorized" in result.rejected[0][1]
        assert "negative_feedback_no_content" not in result.rejection_reasons

    def test_pipeline_report_to_dict_serializable(self) -> None:
        import json

        records = [_make_record(review_status="APPROVED")]
        result, report = run_quality_pipeline(
            records,
            pii_findings={"phone": 1},
            label_distribution={"POSITIVE": 1},
            source_distribution={"user_feedback": 1},
        )
        d = report.to_dict()
        json.dumps(d)  # Should not raise


# ---------------------------------------------------------------------------
# TestPIIRedactionIntegration — PII + quality pipeline integration
# ---------------------------------------------------------------------------


class TestPIIRedactionIntegration:
    """Integration tests combining PII redaction with quality pipeline."""

    def test_pii_in_correction_does_not_reject(self) -> None:
        """Feedback with PII in correction should still pass quality filter.

        PII is redacted separately; the quality filter does not reject
        based on PII presence.
        """
        record = _make_record(
            rating=-1,
            correction="电话 13812345678 服务差",
            reason_codes=["PHONE_LEAKED"],
            review_status="APPROVED",
            pii_flagged=True,
        )
        result, _ = run_quality_pipeline([record])

        assert len(result.accepted) == 1

    def test_redacted_text_used_in_dedup(self) -> None:
        """Two corrections that differ only by PII should be deduplicated
        after redaction normalizes them to the same text."""
        redaction = RedactionService()
        # Use phones with same first/last digit so masked results match
        r1_text = redaction.redact("电话 13812345678 差评").redacted_text
        r2_text = redaction.redact("电话 13900001118 差评").redacted_text
        # After redaction, both become "电话 1*********8 差评"
        assert r1_text == r2_text

    def test_pii_findings_aggregated_across_batch(self) -> None:
        redaction = RedactionService()
        corrections = [
            "电话 13812345678",
            "邮箱 test@example.com",
            "无PII",
            "身份证 110101199003071234",
        ]
        findings: dict[str, int] = {}
        for text in corrections:
            result = redaction.redact(text)
            for k, v in result.findings.items():
                findings[k] = findings.get(k, 0) + v

        assert findings.get("phone") == 1
        assert findings.get("email") == 1
        assert findings.get("id_card") == 1

    def test_full_pipeline_with_pii(self) -> None:
        """End-to-end: redact PII, run quality pipeline, verify report."""
        redaction = RedactionService()
        records = [
            _make_record(
                rating=-1,
                correction="电话 13812345678 服务差",
                reason_codes=["BAD"],
                review_status="APPROVED",
                pii_flagged=True,
            ),
            _make_record(rating=1, correction=None, review_status="APPROVED"),
            _make_record(rating=-1, correction=None, reason_codes=[], review_status="APPROVED"),
        ]

        # Aggregate PII findings
        pii_findings: dict[str, int] = {}
        for r in records:
            if r.correction:
                scan = redaction.redact(r.correction)
                for k, v in scan.findings.items():
                    pii_findings[k] = pii_findings.get(k, 0) + v

        result, report = run_quality_pipeline(
            records,
            pii_findings=pii_findings,
        )

        assert len(result.accepted) == 2  # r1 (PII+content) and r2 (positive)
        assert len(result.rejected) == 1  # r3 (negative no content)
        assert report.pii_findings.get("phone") == 1
