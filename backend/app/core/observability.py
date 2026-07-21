"""JSON logging, secret redaction and dependency-free Prometheus metrics."""

import json
import logging
import re
import threading
from collections import defaultdict
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_conversation_id: ContextVar[str | None] = ContextVar("conversation_id", default=None)

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|authorization|token|api[_-]?key|secret|private_?key)",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?:[\"']?)(password|passwd|authorization|access_?token|refresh_?token|token|"
    r"api[_-]?key|secret|private_?key)(?:[\"']?)\s*[:=]\s*"
    r"(?:bearer\s+[A-Za-z0-9._~+/=-]+|\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_URL_CREDENTIAL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/@\s]+:)[^@\s/]+(@)")
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)


def redact_text(value: object) -> str:
    text = str(value)
    text = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _JWT.sub("[REDACTED_JWT]", text)
    text = _OPENAI_KEY.sub("[REDACTED_KEY]", text)
    text = _AWS_ACCESS_KEY.sub("[REDACTED_KEY]", text)
    text = _URL_CREDENTIAL.sub(r"\1[REDACTED]\2", text)
    return _PEM_PRIVATE_KEY.sub("[REDACTED_PRIVATE_KEY]", text)


def redact_sensitive_data(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact secret-bearing keys without mutating the source value."""
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_sensitive_data(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return redact_text(bytes(value).decode("utf-8", errors="replace"))
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact_text(value)


class JsonLogFormatter(logging.Formatter):
    """Emit one safe JSON object per log record with stable tracing fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "request_id": _record_or_context(record, "request_id", _request_id),
            "user_id": _record_or_context(record, "user_id", _user_id),
            "conversation_id": _record_or_context(record, "conversation_id", _conversation_id),
            "latency_ms": getattr(record, "latency_ms", None),
        }
        details = getattr(record, "details", None)
        if details is not None:
            payload["details"] = redact_sensitive_data(details)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_json_logging(level: str = "INFO") -> None:
    """Install exactly one application JSON handler on the process root logger."""
    root = logging.getLogger()
    normalized_level = getattr(logging, level.strip().upper(), logging.INFO)
    root.setLevel(normalized_level)
    for handler in root.handlers:
        if getattr(handler, "_local_life_json_handler", False):
            handler.setLevel(normalized_level)
            return
    handler = logging.StreamHandler()
    handler.setLevel(normalized_level)
    handler.setFormatter(JsonLogFormatter())
    handler._local_life_json_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def bind_log_context(
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> list[tuple[ContextVar[str | None], Token[str | None]]]:
    bound: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    for variable, value in (
        (_request_id, request_id),
        (_user_id, user_id),
        (_conversation_id, conversation_id),
    ):
        if value is not None:
            bound.append((variable, variable.set(value)))
    return bound


def reset_log_context(tokens: list[tuple[ContextVar[str | None], Token[str | None]]]) -> None:
    for variable, token in reversed(tokens):
        variable.reset(token)


def _record_or_context(
    record: logging.LogRecord,
    field: str,
    variable: ContextVar[str | None],
) -> str | None:
    value = getattr(record, field, None)
    return str(value) if value is not None else variable.get()


class MetricsRegistry:
    """Small in-process registry for HTTP and model invocation metrics."""

    LATENCY_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_count: dict[tuple[str, str, str], int] = defaultdict(int)
        self._request_latency: dict[tuple[str, str], _HistogramState] = defaultdict(
            lambda: _HistogramState(len(self.LATENCY_BUCKETS))
        )
        self._model_count: dict[tuple[str, str], int] = defaultdict(int)
        self._model_latency: dict[str, _HistogramState] = defaultdict(
            lambda: _HistogramState(len(self.LATENCY_BUCKETS))
        )
        self._model_tokens: dict[tuple[str, str], int] = defaultdict(int)

    def observe_request(self, method: str, route: str, status_code: int, latency_ms: float) -> None:
        labels = (method.upper(), route, str(status_code))
        with self._lock:
            self._request_count[labels] += 1
            self._request_latency[labels[:2]].observe(
                max(latency_ms, 0.0) / 1000, self.LATENCY_BUCKETS
            )

    def observe_model_call(
        self,
        *,
        model: str,
        result: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        safe_model = _metric_label(model)
        safe_result = _metric_label(result)
        with self._lock:
            self._model_count[(safe_model, safe_result)] += 1
            self._model_latency[safe_model].observe(
                max(latency_ms, 0.0) / 1000, self.LATENCY_BUCKETS
            )
            self._model_tokens[(safe_model, "prompt")] += max(prompt_tokens, 0)
            self._model_tokens[(safe_model, "completion")] += max(completion_tokens, 0)

    def render_prometheus(self) -> str:
        with self._lock:
            request_count = dict(self._request_count)
            request_latency = {
                key: state.snapshot() for key, state in self._request_latency.items()
            }
            model_count = dict(self._model_count)
            model_latency = {key: state.snapshot() for key, state in self._model_latency.items()}
            model_tokens = dict(self._model_tokens)

        lines = [
            "# HELP local_life_http_requests_total HTTP requests processed.",
            "# TYPE local_life_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(request_count.items()):
            lines.append(
                "local_life_http_requests_total"
                f'{{method="{method}",route="{_escape_label(route)}",status="{status}"}} {count}'
            )
        lines.extend(
            _render_histograms(
                "local_life_http_request_duration_seconds",
                "HTTP request latency.",
                request_latency,
                ("method", "route"),
                self.LATENCY_BUCKETS,
            )
        )
        lines.extend(
            [
                "# HELP local_life_model_calls_total Model calls by result.",
                "# TYPE local_life_model_calls_total counter",
            ]
        )
        for (model, result), count in sorted(model_count.items()):
            lines.append(
                f'local_life_model_calls_total{{model="{model}",result="{result}"}} {count}'
            )
        lines.extend(
            _render_histograms(
                "local_life_model_call_duration_seconds",
                "Model call latency.",
                {(model,): values for model, values in model_latency.items()},
                ("model",),
                self.LATENCY_BUCKETS,
            )
        )
        lines.extend(
            [
                "# HELP local_life_model_tokens_total Model tokens consumed.",
                "# TYPE local_life_model_tokens_total counter",
            ]
        )
        for (model, token_type), count in sorted(model_tokens.items()):
            lines.append(
                f'local_life_model_tokens_total{{model="{model}",type="{token_type}"}} {count}'
            )
        return "\n".join(lines) + "\n"


def _render_histograms(
    name: str,
    help_text: str,
    observations: dict[tuple[str, ...], tuple[tuple[int, ...], float, int]],
    label_names: tuple[str, ...],
    buckets_ms: tuple[int, ...],
) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} histogram"]
    for labels, (bucket_counts, total, count) in sorted(observations.items()):
        label_text = ",".join(
            f'{label_name}="{_escape_label(label_value)}"'
            for label_name, label_value in zip(label_names, labels, strict=True)
        )
        for bucket_ms, bucket_count in zip(buckets_ms, bucket_counts, strict=True):
            lines.append(f'{name}_bucket{{{label_text},le="{bucket_ms / 1000:g}"}} {bucket_count}')
        lines.append(f'{name}_bucket{{{label_text},le="+Inf"}} {count}')
        lines.append(f"{name}_sum{{{label_text}}} {total:.6f}")
        lines.append(f"{name}_count{{{label_text}}} {count}")
    return lines


@dataclass(slots=True)
class _HistogramState:
    bucket_count: int
    buckets: list[int] = field(init=False)
    total: float = 0.0
    count: int = 0

    def __post_init__(self) -> None:
        self.buckets = [0] * self.bucket_count

    def observe(self, value: float, buckets_ms: tuple[int, ...]) -> None:
        self.total += value
        self.count += 1
        for index, bucket_ms in enumerate(buckets_ms):
            if value <= bucket_ms / 1000:
                self.buckets[index] += 1

    def snapshot(self) -> tuple[tuple[int, ...], float, int]:
        return tuple(self.buckets), self.total, self.count


def _metric_label(value: str) -> str:
    return redact_text(value).strip()[:100] or "unknown"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
