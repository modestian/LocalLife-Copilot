"""Configurable record cleaning and structured row rendering."""

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.etl.loaders import normalized_content_hash
from app.etl.models import CleanStatus, DocumentRecord, JsonValue, Metadata

CustomCleaningFunction = Callable[[JsonValue, Mapping[str, JsonValue]], JsonValue]


class CleaningConfigError(ValueError):
    """Raised when a cleaning pipeline configuration is invalid."""


class RowTemplateError(ValueError):
    """Raised when a structured row cannot be rendered with its configured template."""


@dataclass(frozen=True, slots=True)
class CleaningStepReport:
    step_type: str
    input_count: int
    output_count: int
    duration_ms: float
    error_samples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CleaningReport:
    input_count: int
    output_count: int
    steps: tuple[CleaningStepReport, ...]


class CleaningFunctionRegistry:
    """Explicit server-side allowlist for custom value cleaning functions."""

    def __init__(self) -> None:
        self._functions: dict[str, CustomCleaningFunction] = {}

    def register(self, name: str, function: CustomCleaningFunction) -> None:
        normalized_name = name.strip()
        if not normalized_name:
            raise CleaningConfigError("custom cleaning function name must not be blank")
        if normalized_name in self._functions:
            raise CleaningConfigError(f"custom cleaning function already registered: {name}")
        self._functions[normalized_name] = function

    def resolve(self, name: str) -> CustomCleaningFunction:
        try:
            return self._functions[name]
        except KeyError as exc:
            raise CleaningConfigError(
                f"custom cleaning function is not allowlisted: {name}"
            ) from exc


def _row_data(record: DocumentRecord) -> dict[str, JsonValue] | None:
    value = record.metadata.get("row_data")
    return dict(value) if isinstance(value, dict) else None


def _value(record: DocumentRecord, column: str) -> JsonValue:
    row = _row_data(record)
    if row is not None and column in row:
        return row[column]
    if column == "content":
        return record.content
    if column == "source_key":
        return record.source_key
    return record.metadata.get(column)


def _with_value(record: DocumentRecord, column: str, value: JsonValue) -> DocumentRecord:
    if column == "source_key":
        raise CleaningConfigError("source_key cannot be changed by a cleaning step")
    metadata: Metadata = dict(record.metadata)
    row = _row_data(record)
    if row is not None and (column in row or column not in metadata):
        row[column] = value
        metadata["row_data"] = row
        content = json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return replace(
            record,
            metadata=metadata,
            content=content,
            content_hash=normalized_content_hash(content),
        )
    if column == "content":
        content = "" if value is None else str(value)
        return replace(record, content=content, content_hash=normalized_content_hash(content))
    metadata[column] = value
    return replace(record, metadata=metadata)


def _columns(config: Mapping[str, Any]) -> tuple[str, ...]:
    raw = config.get("subset", config.get("column"))
    if isinstance(raw, str):
        values = (raw,)
    elif isinstance(raw, Sequence) and not isinstance(raw, bytes):
        values = tuple(raw)
    else:
        raise CleaningConfigError("subset must be a non-empty string list")
    if not values or any(not isinstance(item, str) or not item.strip() for item in values):
        raise CleaningConfigError("subset must be a non-empty string list")
    return values


def _dedupe_key(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ConfigurableCleaner:
    """Run YAML-shaped cleaning steps in declaration order."""

    def __init__(
        self,
        cleaning_steps: Sequence[Mapping[str, Any]],
        *,
        text_template: str | None = None,
        custom_functions: CleaningFunctionRegistry | None = None,
        max_error_samples: int = 10,
    ) -> None:
        if max_error_samples < 0:
            raise CleaningConfigError("max_error_samples must be greater than or equal to zero")
        self._steps = tuple(dict(step) for step in cleaning_steps)
        self._text_template = text_template
        self._custom_functions = custom_functions or CleaningFunctionRegistry()
        self._max_error_samples = max_error_samples
        self.last_report: CleaningReport | None = None
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        supported = {"regex", "dropna", "fillna", "drop_duplicates", "custom"}
        for config in self._steps:
            step_type = config.get("type")
            if step_type not in supported:
                raise CleaningConfigError(f"unsupported cleaning step type: {step_type!r}")
            if step_type == "regex":
                column, pattern = config.get("column"), config.get("pattern")
                if not isinstance(column, str) or not column.strip():
                    raise CleaningConfigError("regex column must be a non-blank string")
                if not isinstance(pattern, str):
                    raise CleaningConfigError("regex pattern must be a string")
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise CleaningConfigError(f"invalid regex pattern: {pattern}") from exc
            elif step_type in {"dropna", "drop_duplicates"}:
                _columns(config)
            elif step_type == "fillna":
                if "values" in config:
                    if not isinstance(config["values"], Mapping) or not config["values"]:
                        raise CleaningConfigError("fillna values must be a non-empty mapping")
                else:
                    _columns(config)
                    if "value" not in config:
                        raise CleaningConfigError("fillna requires value or values")
            else:
                name, column = config.get("name"), config.get("column")
                if not isinstance(name, str) or not name.strip():
                    raise CleaningConfigError("custom name must be a non-blank string")
                if not isinstance(column, str) or not column.strip():
                    raise CleaningConfigError("custom column must be a non-blank string")
                self._custom_functions.resolve(name)

    def clean(self, records: Iterable[DocumentRecord]) -> list[DocumentRecord]:
        current = list(records)
        initial_count = len(current)
        reports: list[CleaningStepReport] = []
        for config in self._steps:
            started = time.perf_counter()
            before = len(current)
            current, errors = self._apply_step(current, config)
            reports.append(
                CleaningStepReport(
                    str(config["type"]),
                    before,
                    len(current),
                    (time.perf_counter() - started) * 1000,
                    tuple(errors[: self._max_error_samples]),
                )
            )
        if self._text_template is not None:
            started = time.perf_counter()
            before = len(current)
            current = [render_row_template(record, self._text_template) for record in current]
            reports.append(
                CleaningStepReport(
                    "row_template", before, len(current), (time.perf_counter() - started) * 1000
                )
            )
        self.last_report = CleaningReport(initial_count, len(current), tuple(reports))
        return current

    def _apply_step(
        self, records: list[DocumentRecord], config: Mapping[str, Any]
    ) -> tuple[list[DocumentRecord], list[str]]:
        step_type = config["type"]
        if step_type == "dropna":
            subset = _columns(config)
            return [r for r in records if all(_value(r, c) is not None for c in subset)], []
        if step_type == "fillna":
            raw_values = config.get("values")
            values = (
                dict(raw_values)
                if isinstance(raw_values, Mapping)
                else {column: config["value"] for column in _columns(config)}
            )
            result = records
            for column, value in values.items():
                if not isinstance(column, str):
                    raise CleaningConfigError("fillna values keys must be strings")
                result = [
                    _with_value(record, column, value) if _value(record, column) is None else record
                    for record in result
                ]
            return result, []
        if step_type == "drop_duplicates":
            subset, seen, result = _columns(config), set(), []
            for record in records:
                key = tuple(_dedupe_key(_value(record, column)) for column in subset)
                if key not in seen:
                    seen.add(key)
                    result.append(record)
            return result, []
        if step_type == "regex":
            pattern = re.compile(config["pattern"])
            replacement, column = config.get("replace_with", ""), config["column"]
            if not isinstance(replacement, str):
                raise CleaningConfigError("regex replace_with must be a string")
            return [
                _with_value(record, column, pattern.sub(replacement, value))
                if isinstance((value := _value(record, column)), str)
                else record
                for record in records
            ], []

        function = self._custom_functions.resolve(config["name"])
        column, raw_options = config["column"], config.get("options", {})
        if not isinstance(raw_options, Mapping):
            raise CleaningConfigError("custom options must be a mapping")
        result, errors = [], []
        for record in records:
            try:
                result.append(
                    _with_value(record, column, function(_value(record, column), raw_options))
                )
            except Exception:
                errors.append(record.source_key)
                result.append(replace(record, clean_status=CleanStatus.REVIEW_REQUIRED))
        return result, errors


def render_row_template(record: DocumentRecord, template: str) -> DocumentRecord:
    """Render one structured loader record into natural language."""
    row = _row_data(record)
    if row is None:
        raise RowTemplateError(f"record has no structured row_data: {record.source_key}")
    values: dict[str, JsonValue] = dict(record.metadata)
    values.update(row)
    values["source_key"] = record.source_key
    values = {key: "" if value is None else value for key, value in values.items()}
    try:
        content = template.format_map(values)
    except (KeyError, ValueError) as exc:
        raise RowTemplateError(
            f"could not render row template for {record.source_key}: {exc}"
        ) from exc
    return replace(record, content=content, content_hash=normalized_content_hash(content))
