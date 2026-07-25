"""Embedding gateway adapter and validated batching service."""

import json
import math
from collections.abc import Sequence
from time import perf_counter, sleep
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.observability import MetricsRegistry


class EmbeddingError(RuntimeError):
    """Stable embedding failure suitable for worker task reporting."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class HttpEmbeddingProvider:
    """Call the model gateway using an OpenAI-compatible embeddings contract."""

    def __init__(
        self,
        url: str,
        *,
        model: str,
        timeout_seconds: float,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.25,
        metrics_registry: MetricsRegistry | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")
        self._url = url
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._metrics_registry = metrics_registry

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        started_at = perf_counter()
        payload = json.dumps({"model": self._model, "input": list(texts)}).encode()
        request = Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                    body = json.load(response)
                break
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    sleep(self._retry_delay_seconds * attempt)
        else:
            self._observe("FAILED", started_at)
            error_type = type(last_error).__name__ if last_error is not None else "unknown"
            raise EmbeddingError(
                "EMBEDDING_GATEWAY_FAILED",
                f"embedding gateway request failed after {self._max_attempts} attempts "
                f"({error_type})",
            ) from last_error

        try:
            data = sorted(body["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
        except (KeyError, TypeError) as exc:
            self._observe("FAILED", started_at)
            raise EmbeddingError(
                "EMBEDDING_RESPONSE_INVALID", "embedding gateway returned an invalid response"
            ) from exc
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        prompt_tokens = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
        self._observe("SUCCEEDED", started_at, prompt_tokens=prompt_tokens)
        return vectors

    def _observe(self, result: str, started_at: float, *, prompt_tokens: object = 0) -> None:
        if self._metrics_registry is None:
            return
        safe_prompt_tokens = prompt_tokens if isinstance(prompt_tokens, int) else 0
        self._metrics_registry.observe_model_call(
            model=self._model,
            result=result,
            latency_ms=(perf_counter() - started_at) * 1000,
            prompt_tokens=safe_prompt_tokens,
        )


class BatchedEmbedder:
    """Generate embeddings in bounded batches and validate the complete result."""

    def __init__(self, provider: EmbeddingProvider, *, dimension: int, batch_size: int) -> None:
        if dimension <= 0:
            raise ValueError("embedding dimension must be greater than zero")
        if batch_size <= 0:
            raise ValueError("embedding batch size must be greater than zero")
        self._provider = provider
        self._dimension = dimension
        self._batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = texts[offset : offset + self._batch_size]
            received = self._provider.embed(batch)
            if len(received) != len(batch):
                raise EmbeddingError(
                    "EMBEDDING_COUNT_MISMATCH",
                    f"expected {len(batch)} embeddings but received {len(received)}",
                )
            vectors.extend(
                self._validate_vector(vector, offset + index)
                for index, vector in enumerate(received)
            )
        return vectors

    def _validate_vector(self, vector: Sequence[float], index: int) -> list[float]:
        if len(vector) != self._dimension:
            raise EmbeddingError(
                "EMBEDDING_DIMENSION_MISMATCH",
                f"embedding {index} has dimension {len(vector)}; expected {self._dimension}",
            )
        normalized: list[float] = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise EmbeddingError(
                    "EMBEDDING_VECTOR_INVALID", f"embedding {index} contains a non-numeric value"
                )
            number = float(value)
            if not math.isfinite(number):
                raise EmbeddingError(
                    "EMBEDDING_VECTOR_INVALID", f"embedding {index} contains a non-finite value"
                )
            normalized.append(number)
        return normalized
