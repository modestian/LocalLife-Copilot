"""Unit tests for review reply generation and compliance constraints."""

from fastapi.testclient import TestClient

from app.application.reply_generator import (
    ReplyGenerator,
    check_compliance,
)

# ---------------------------------------------------------------------------
# Compliance checker tests
# ---------------------------------------------------------------------------


class TestComplianceChecker:
    def test_clean_text_passes(self) -> None:
        text = "感谢您的反馈，我们会持续改进。"
        assert check_compliance(text) == []

    def test_refund_amount_detected(self) -> None:
        assert check_compliance("已为您退款50元")
        assert check_compliance("退您30元")
        assert check_compliance("退还100")

    def test_discount_detected(self) -> None:
        assert check_compliance("下次给您8折优惠")
        assert check_compliance("满200减50")
        assert check_compliance("本次免单")

    def test_fabricated_compensation_detected(self) -> None:
        assert check_compliance("已为您发放优惠券")
        assert check_compliance("已退款至您的账户")
        assert check_compliance("已补偿您20元")
        assert check_compliance("赠送菜品一份")

    def test_deflection_detected(self) -> None:
        assert check_compliance("这是第三方配送的责任")
        assert check_compliance("此事与我们无关")
        assert check_compliance("不是我们的问题")

    def test_multiple_violations(self) -> None:
        text = "已为您退款50元，下次8折，赠送菜品一份"
        violations = check_compliance(text)
        assert len(violations) >= 3


# ---------------------------------------------------------------------------
# ReplyGenerator tests
# ---------------------------------------------------------------------------


class TestReplyGeneratorPositive:
    def test_positive_reply(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="味道很好，服务周到",
            sentiment="POSITIVE",
            aspect_labels=["taste", "attitude"],
        )
        assert result.compliance_passed
        assert result.template_id == "positive_default"
        assert "口味" in result.reply_text
        assert "服务态度" in result.reply_text

    def test_positive_without_aspects(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="非常好吃",
            sentiment="POSITIVE",
            aspect_labels=["taste"],
        )
        assert result.compliance_passed
        assert "口味" in result.reply_text


class TestReplyGeneratorNeutral:
    def test_neutral_reply(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="环境一般，价格偏贵",
            sentiment="NEUTRAL",
            aspect_labels=["decoration", "price"],
        )
        assert result.compliance_passed
        assert result.template_id == "neutral_default"
        assert "装修环境" in result.reply_text
        assert "价格" in result.reply_text


class TestReplyGeneratorNegative:
    def test_negative_specific_reason_slow_wait(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="等太久了，上菜慢",
            sentiment="NEGATIVE",
            aspect_labels=["waiting_time"],
            negative_reasons=["slow_wait"],
        )
        assert result.template_id == "neg_slow_wait"
        assert result.compliance_passed
        assert "久等" in result.reply_text

    def test_negative_specific_reason_rude_staff(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="服务员态度差",
            sentiment="NEGATIVE",
            aspect_labels=["attitude"],
            negative_reasons=["rude_staff"],
        )
        assert result.template_id == "neg_rude_staff"
        assert result.compliance_passed
        assert "培训" in result.reply_text

    def test_negative_specific_reason_taste_bad(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="菜太难吃了",
            sentiment="NEGATIVE",
            aspect_labels=["taste"],
            negative_reasons=["taste_bad"],
        )
        assert result.template_id == "neg_taste_bad"
        assert result.compliance_passed

    def test_negative_fallback_no_reason_match(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="整体体验不好",
            sentiment="NEGATIVE",
            aspect_labels=["overall"],
            negative_reasons=["unknown_reason"],
        )
        assert result.template_id == "negative_default"
        assert result.compliance_passed

    def test_negative_fallback_no_reasons(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="不好",
            sentiment="NEGATIVE",
            aspect_labels=[],
            negative_reasons=[],
        )
        assert result.template_id == "negative_default"
        assert result.compliance_passed

    def test_negative_multiple_reasons_picks_first(self) -> None:
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="等太久了，态度差，难吃",
            sentiment="NEGATIVE",
            aspect_labels=["waiting_time", "attitude", "taste"],
            negative_reasons=["slow_wait", "rude_staff", "taste_bad"],
        )
        # Should pick the first matching reason's template
        assert result.template_id == "neg_slow_wait"
        assert result.compliance_passed

    def test_aspect_extraction_from_text(self) -> None:
        """When aspect_labels is empty, extract from review_text."""
        gen = ReplyGenerator()
        result = gen.generate(
            review_text="味道很好",
            sentiment="POSITIVE",
            aspect_labels=[],
        )
        assert result.compliance_passed
        # AspectExtractor should find "taste" from "味道"
        assert "口味" in result.reply_text


class TestReplyGeneratorCompliance:
    def test_all_templates_are_compliant(self) -> None:
        """Every template in the library must pass compliance check."""
        from app.application.reply_generator import REPLY_TEMPLATES

        gen = ReplyGenerator()
        for tpl in REPLY_TEMPLATES:
            result = gen.generate(
                review_text="测试",
                sentiment=tpl.sentiment,
                aspect_labels=["taste", "service"],
                negative_reasons=[tpl.negative_reason] if tpl.negative_reason else [],
            )
            assert result.compliance_passed, (
                f"Template {tpl.template_id} failed compliance: {result.violations}"
            )


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _create_test_client() -> TestClient:
    """Create a minimal FastAPI TestClient for reply endpoint tests."""
    from fastapi import FastAPI

    from app.api.analytics import router as analytics_router
    from app.core.api import install_api_contract
    from app.core.config import get_settings

    app = FastAPI()
    settings = get_settings()
    app.state.settings = settings
    install_api_contract(app, settings)
    app.include_router(analytics_router, prefix=settings.api_v1_prefix)
    return TestClient(app)


class TestReplyEndpoint:
    def test_positive_reply_success(self) -> None:
        client = _create_test_client()
        response = client.post(
            "/api/v1/merchants/M001/analytics/reply",
            json={
                "review_text": "味道很好",
                "sentiment": "POSITIVE",
                "aspect_labels": ["taste"],
                "negative_reasons": [],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        data = body["data"]
        assert data["compliance_passed"] is True
        assert data["template_id"] == "positive_default"
        assert "reply_text" in data
        assert "violations" in data

    def test_negative_reply_with_reason(self) -> None:
        client = _create_test_client()
        response = client.post(
            "/api/v1/merchants/M001/analytics/reply",
            json={
                "review_text": "上菜太慢了",
                "sentiment": "NEGATIVE",
                "aspect_labels": ["waiting_time"],
                "negative_reasons": ["slow_wait"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["template_id"] == "neg_slow_wait"
        assert body["data"]["compliance_passed"] is True

    def test_empty_review_text_rejected(self) -> None:
        client = _create_test_client()
        response = client.post(
            "/api/v1/merchants/M001/analytics/reply",
            json={
                "review_text": "",
                "sentiment": "POSITIVE",
                "aspect_labels": [],
                "negative_reasons": [],
            },
        )
        assert response.status_code == 400

    def test_invalid_sentiment_rejected(self) -> None:
        client = _create_test_client()
        response = client.post(
            "/api/v1/merchants/M001/analytics/reply",
            json={
                "review_text": "测试",
                "sentiment": "UNKNOWN",
                "aspect_labels": [],
                "negative_reasons": [],
            },
        )
        assert response.status_code == 400

    def test_missing_body_field_rejected(self) -> None:
        client = _create_test_client()
        response = client.post(
            "/api/v1/merchants/M001/analytics/reply",
            json={
                "review_text": "测试",
                # missing sentiment
                "aspect_labels": [],
                "negative_reasons": [],
            },
        )
        assert response.status_code == 422

    def test_neutral_reply(self) -> None:
        client = _create_test_client()
        response = client.post(
            "/api/v1/merchants/M001/analytics/reply",
            json={
                "review_text": "环境一般",
                "sentiment": "NEUTRAL",
                "aspect_labels": ["decoration"],
                "negative_reasons": [],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["template_id"] == "neutral_default"
