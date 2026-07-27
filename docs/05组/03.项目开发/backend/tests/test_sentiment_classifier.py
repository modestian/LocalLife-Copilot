from unittest.mock import patch

import pytest

from app.analytics import AspectExtractor, SentimentAnalyzer, SentimentClassifier, SentimentResult


class TestSentimentResult:
    def test_confidence_validation(self):
        result = SentimentResult(sentiment="POSITIVE", confidence=0.95, model_version="test")
        assert 0.0 <= result.confidence <= 1.0
        assert result.confidence == 0.95

    def test_confidence_rounding(self):
        result = SentimentResult(sentiment="NEUTRAL", confidence=0.1234567, model_version="test")
        assert result.confidence == 0.1235


class TestNeutralCalibration:
    """Tests for margin-based neutral calibration logic."""

    def test_clear_positive_stays_positive(self):
        clf = SentimentClassifier()
        scores = [
            {"label": "POSITIVE", "score": 0.95},
            {"label": "NEUTRAL", "score": 0.03},
            {"label": "NEGATIVE", "score": 0.02},
        ]
        label, score = clf._calibrate_neutral(scores)
        assert label == "POSITIVE"
        assert score == pytest.approx(0.95)

    def test_borderline_positive_becomes_neutral(self):
        clf = SentimentClassifier()
        # margin = 0.80 - 0.65 = 0.15 < 0.25 threshold
        scores = [
            {"label": "POSITIVE", "score": 0.80},
            {"label": "NEUTRAL", "score": 0.65},
            {"label": "NEGATIVE", "score": 0.05},
        ]
        label, score = clf._calibrate_neutral(scores)
        assert label == "NEUTRAL"

    def test_clear_neutral_stays_neutral(self):
        clf = SentimentClassifier()
        scores = [
            {"label": "NEUTRAL", "score": 0.90},
            {"label": "POSITIVE", "score": 0.05},
            {"label": "NEGATIVE", "score": 0.05},
        ]
        label, score = clf._calibrate_neutral(scores)
        assert label == "NEUTRAL"

    def test_clear_negative_stays_negative(self):
        clf = SentimentClassifier()
        scores = [
            {"label": "NEGATIVE", "score": 0.92},
            {"label": "NEUTRAL", "score": 0.04},
            {"label": "POSITIVE", "score": 0.04},
        ]
        label, score = clf._calibrate_neutral(scores)
        assert label == "NEGATIVE"

    def test_empty_scores_returns_neutral(self):
        clf = SentimentClassifier()
        label, score = clf._calibrate_neutral([])
        assert label == "NEUTRAL"
        assert score == 0.0

    def test_custom_threshold_via_env(self, monkeypatch):
        monkeypatch.setenv("SENTIMENT_NEUTRAL_MARGIN", "0.50")
        clf = SentimentClassifier()
        # margin = 0.90 - 0.60 = 0.30 < 0.50 threshold
        scores = [
            {"label": "POSITIVE", "score": 0.90},
            {"label": "NEUTRAL", "score": 0.60},
        ]
        label, _ = clf._calibrate_neutral(scores)
        assert label == "NEUTRAL"

    def test_parse_pipeline_scores_nested_list(self):
        clf = SentimentClassifier()
        raw = [[{"label": "POSITIVE", "score": 0.9}, {"label": "NEUTRAL", "score": 0.1}]]
        scores = clf._parse_pipeline_scores(raw)
        assert len(scores) == 2
        assert scores[0]["label"] == "POSITIVE"

    def test_parse_pipeline_scores_flat_list(self):
        clf = SentimentClassifier()
        raw = [{"label": "POSITIVE", "score": 0.9}, {"label": "NEUTRAL", "score": 0.1}]
        scores = clf._parse_pipeline_scores(raw)
        assert len(scores) == 2

    def test_parse_pipeline_scores_empty(self):
        clf = SentimentClassifier()
        scores = clf._parse_pipeline_scores([])
        assert len(scores) == 1
        assert scores[0]["label"] == "NEUTRAL"


class TestModelReference:
    def test_hugging_face_id_is_not_converted_to_local_path(self):
        classifier = SentimentClassifier(model_name="organization/model")
        assert classifier._resolve_model_reference() == "organization/model"

    def test_missing_absolute_model_path_fails_clearly(self, tmp_path):
        classifier = SentimentClassifier(model_name=str(tmp_path / "missing-model"))
        with pytest.raises(FileNotFoundError, match="training/README.md"):
            classifier._resolve_model_reference()


class TestAspectExtractor:
    def test_extract_aspects_basic(self):
        text = "这家店口味很好，价格实惠，环境干净"
        aspects = AspectExtractor.extract_aspects(text)
        assert "taste" in aspects
        assert "price" in aspects
        assert "hygiene" in aspects

    def test_extract_aspects_empty(self):
        aspects = AspectExtractor.extract_aspects("")
        assert aspects == []

    def test_extract_aspects_none(self):
        aspects = AspectExtractor.extract_aspects(None)
        assert aspects == []

    def test_extract_negative_reasons(self):
        text = "等太久了，服务员态度差"
        reasons = AspectExtractor.extract_negative_reasons(text)
        assert "slow_wait" in reasons
        assert "rude_staff" in reasons

    def test_extract_negative_reasons_empty(self):
        reasons = AspectExtractor.extract_negative_reasons("")
        assert reasons == []


class TestSentimentAnalyzer:
    def test_version_property(self):
        analyzer = SentimentAnalyzer()
        assert analyzer.version == "unknown"

    @patch("app.analytics.sentiment_classifier.SentimentClassifier.predict_single")
    def test_analyze_single_output_format(self, mock_predict):
        mock_predict.return_value = SentimentResult(
            sentiment="POSITIVE", confidence=0.95, model_version="test"
        )
        analyzer = SentimentAnalyzer()
        text = "这家餐厅很好吃，服务态度也很好"
        result = analyzer.analyze_single(text)
        assert isinstance(result, SentimentResult)
        assert result.sentiment == "POSITIVE"
        assert result.confidence == 0.95
        assert "taste" in result.aspect_labels
        assert "attitude" in result.aspect_labels
        assert result.negative_reason == []

    def test_analyze_single_empty_text(self):
        analyzer = SentimentAnalyzer()
        result = analyzer.analyze_single("")
        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0

    def test_analyze_single_none(self):
        analyzer = SentimentAnalyzer()
        result = analyzer.analyze_single(None)
        assert result.sentiment == "NEUTRAL"
        assert result.confidence == 0.0

    @patch("app.analytics.sentiment_classifier.SentimentClassifier.predict_batch")
    def test_analyze_batch_empty(self, mock_predict):
        mock_predict.return_value = []
        analyzer = SentimentAnalyzer()
        results = analyzer.analyze_batch([])
        assert results == []

    @patch("app.analytics.sentiment_classifier.SentimentClassifier.predict_batch")
    def test_analyze_batch_basic(self, mock_predict):
        mock_predict.return_value = [
            SentimentResult(sentiment="POSITIVE", confidence=0.95, model_version="test"),
            SentimentResult(sentiment="NEUTRAL", confidence=0.5, model_version="test"),
            SentimentResult(sentiment="NEGATIVE", confidence=0.9, model_version="test"),
        ]
        analyzer = SentimentAnalyzer()
        texts = ["这家店很好吃", "一般般吧", "太难吃了，再也不来了"]
        results = analyzer.analyze_batch(texts)
        assert len(results) == 3
        for result in results:
            assert isinstance(result, SentimentResult)

    @patch("app.analytics.sentiment_classifier.SentimentClassifier.predict_batch")
    def test_analyze_batch_mixed_validity(self, mock_predict):
        mock_predict.return_value = [
            SentimentResult(sentiment="POSITIVE", confidence=0.95, model_version="test"),
            SentimentResult(sentiment="NEUTRAL", confidence=0.0, model_version="test"),
            SentimentResult(sentiment="NEUTRAL", confidence=0.0, model_version="test"),
            SentimentResult(sentiment="NEUTRAL", confidence=0.5, model_version="test"),
        ]
        analyzer = SentimentAnalyzer()
        texts = ["好吃", "", None, "还行"]
        results = analyzer.analyze_batch(texts)
        assert len(results) == 4
        assert results[1].sentiment == "NEUTRAL"
        assert results[1].confidence == 0.0
        assert results[2].sentiment == "NEUTRAL"
        assert results[2].confidence == 0.0
