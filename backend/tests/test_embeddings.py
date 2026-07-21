import json
from collections.abc import Sequence
from io import BytesIO

import pytest

from app.core.observability import MetricsRegistry
from app.etl.embeddings import BatchedEmbedder, EmbeddingError, HttpEmbeddingProvider


class RecordingProvider:
    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls.append(list(texts))
        return [[float(index)] * self.dimension for index, _ in enumerate(texts)]


def test_batched_embedder_bounds_requests_and_preserves_order() -> None:
    provider = RecordingProvider()
    embedder = BatchedEmbedder(provider, dimension=3, batch_size=2)

    vectors = embedder.embed(["a", "b", "c", "d", "e"])

    assert provider.calls == [["a", "b"], ["c", "d"], ["e"]]
    assert vectors == [[0.0] * 3, [1.0] * 3, [0.0] * 3, [1.0] * 3, [0.0] * 3]


def test_http_embedding_provider_uses_gateway_contract_and_response_indexes(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return BytesIO(
            json.dumps(
                {
                    "data": [
                        {"index": 1, "embedding": [2.0]},
                        {"index": 0, "embedding": [1.0]},
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr("app.etl.embeddings.urlopen", fake_urlopen)
    provider = HttpEmbeddingProvider(
        "http://gateway/v1/embeddings", model="model-v1", timeout_seconds=3
    )

    assert provider.embed(["a", "b"]) == [[1.0], [2.0]]
    assert captured == {"body": {"model": "model-v1", "input": ["a", "b"]}, "timeout": 3}


def test_http_embedding_provider_records_production_model_metrics(monkeypatch) -> None:
    registry = MetricsRegistry()

    def fake_urlopen(request, timeout):
        del request, timeout
        return BytesIO(
            json.dumps(
                {
                    "data": [{"index": 0, "embedding": [1.0]}],
                    "usage": {"prompt_tokens": 7},
                }
            ).encode()
        )

    monkeypatch.setattr("app.etl.embeddings.urlopen", fake_urlopen)
    provider = HttpEmbeddingProvider(
        "http://gateway/v1/embeddings",
        model="embedding-v1",
        timeout_seconds=3,
        metrics_registry=registry,
    )

    assert provider.embed(["hello"]) == [[1.0]]
    output = registry.render_prometheus()
    assert 'model="embedding-v1",result="SUCCEEDED"} 1' in output
    assert 'model="embedding-v1",type="prompt"} 7' in output


def test_batched_embedder_rejects_wrong_dimension() -> None:
    embedder = BatchedEmbedder(RecordingProvider(dimension=2), dimension=3, batch_size=2)

    with pytest.raises(EmbeddingError) as captured:
        embedder.embed(["a"])

    assert captured.value.code == "EMBEDDING_DIMENSION_MISMATCH"


class MissingVectorProvider:
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return []


def test_batched_embedder_rejects_missing_results() -> None:
    embedder = BatchedEmbedder(MissingVectorProvider(), dimension=3, batch_size=2)

    with pytest.raises(EmbeddingError) as captured:
        embedder.embed(["a"])

    assert captured.value.code == "EMBEDDING_COUNT_MISMATCH"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "bad"])
def test_batched_embedder_rejects_invalid_vector_values(value: object) -> None:
    class InvalidProvider:
        def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
            return [[0.0, value, 1.0]]  # type: ignore[list-item]

    with pytest.raises(EmbeddingError) as captured:
        BatchedEmbedder(InvalidProvider(), dimension=3, batch_size=1).embed(["a"])

    assert captured.value.code == "EMBEDDING_VECTOR_INVALID"
