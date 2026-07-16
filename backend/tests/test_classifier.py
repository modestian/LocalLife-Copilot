import json
from pathlib import Path
from unittest.mock import patch
import pytest
from app.review_analysis import BatchSentimentResult, SentimentResult, get_classifier

def test_classifier_single_prediction_mocked():
    # 清空lru_cache缓存
    get_classifier.cache_clear()
    mock_ret = SentimentResult(
        sentiment="POSITIVE",
        confidence=0.95,
        model_version="test-model-v1",
    )
    with patch("app.review_analysis.classifier.SentimentClassifier") as MockClassifier:
        mock_instance = MockClassifier.return_value
        mock_instance.classify.return_value = mock_ret

        classifier = get_classifier()
        result = classifier.classify("这家店很好吃，推荐大家来！")

        assert isinstance(result, SentimentResult)
        assert result.sentiment == "POSITIVE"
        assert result.confidence == 0.95
        assert result.model_version == "test-model-v1"
        mock_instance.classify.assert_called_once_with("这家店很好吃，推荐大家来！")


def test_classifier_batch_prediction_mocked():
    get_classifier.cache_clear()
    mock_batch_ret = BatchSentimentResult(
        results=[
            SentimentResult(sentiment="POSITIVE", confidence=0.92, model_version="test-model-v1"),
            SentimentResult(sentiment="NEUTRAL", confidence=0.78, model_version="test-model-v1"),
            SentimentResult(sentiment="NEGATIVE", confidence=0.89, model_version="test-model-v1"),
        ],
        model_version="test-model-v1",
        total_count=3,
        processed_count=3,
    )
    with patch("app.review_analysis.classifier.SentimentClassifier") as MockClassifier:
        mock_instance = MockClassifier.return_value
        mock_instance.classify_batch.return_value = mock_batch_ret

        classifier = get_classifier()
        texts = ["味道很棒", "一般般吧", "非常难吃"]
        result = classifier.classify_batch(texts)

        assert isinstance(result, BatchSentimentResult)
        assert result.total_count == 3
        assert result.processed_count == 3
        assert len(result.results) == 3
        mock_instance.classify_batch.assert_called_once_with(texts)


def test_classifier_empty_batch_mocked():
    get_classifier.cache_clear()
    mock_batch_ret = BatchSentimentResult(
        results=[],
        model_version="test-model-v1",
        total_count=0,
        processed_count=0,
    )
    with patch("app.review_analysis.classifier.SentimentClassifier") as MockClassifier:
        mock_instance = MockClassifier.return_value
        mock_instance.classify_batch.return_value = mock_batch_ret

        classifier = get_classifier()
        result = classifier.classify_batch([])

        assert result.total_count == 0
        assert result.processed_count == 0
        assert result.results == []


# 真实模型用例
def test_classifier_single_prediction_real(run_model_tests):
    if not run_model_tests:
        pytest.skip("Requires model download; use --run-model-tests to enable")
    classifier = get_classifier()
    text = "这家店很好吃，推荐大家来！"
    result = classifier.classify(text)

    assert isinstance(result, SentimentResult)
    assert result.sentiment in ["POSITIVE", "NEUTRAL", "NEGATIVE"]
    assert 0.0 <= result.confidence <= 1.0
    assert isinstance(result.model_version, str)
    assert len(result.model_version) > 0


def test_classifier_batch_prediction_real(run_model_tests):
    if not run_model_tests:
        pytest.skip("Requires model download; use --run-model-tests to enable")
    classifier = get_classifier()
    texts = [
        "味道很棒，服务也很好",
        "一般般吧，没什么特别的",
        "非常难吃，不会再来了",
    ]
    result = classifier.classify_batch(texts)

    assert isinstance(result, BatchSentimentResult)
    assert result.total_count == 3
    assert result.processed_count == 3
    assert len(result.results) == 3

    for item in result.results:
        assert item.sentiment in ["POSITIVE", "NEUTRAL", "NEGATIVE"]
        assert 0.0 <= item.confidence <= 1.0


def test_classifier_with_benchmark_sample(run_model_tests):
    if not run_model_tests:
        pytest.skip("Requires model download and benchmark data; use --run-model-tests to enable")
    data_path = Path(__file__).parent / "data" / "benchmark_reviews.jsonl"
    assert data_path.exists(), f"Benchmark data not found: {data_path}"

    with open(data_path, "r", encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    texts = [sample["content"] for sample in samples[:10]]
    classifier = get_classifier()
    result = classifier.classify_batch(texts)

    assert len(result.results) == len(texts)
    for item in result.results:
        assert item.sentiment in ["POSITIVE", "NEUTRAL", "NEGATIVE"]
        assert 0.0 <= item.confidence <= 1.0