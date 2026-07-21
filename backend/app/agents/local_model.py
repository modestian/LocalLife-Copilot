"""Safe local model adapter used when no external chat model is configured."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.contracts import ModelInput, ModelPrediction


class ExtractiveModelAdapter:
    """Produce schema-valid grounded output by copying only supplied evidence."""

    version = "local-extractive-rag-v1"

    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]:
        return tuple(self._predict_one(item) for item in batch)

    def _predict_one(self, item: ModelInput) -> ModelPrediction:
        if item.task.startswith("rag_"):
            structured = _grounded_output(item.task.removeprefix("rag_"), item.prompt)
            return ModelPrediction(
                text=json.dumps(structured, ensure_ascii=False),
                structured=structured,
                model_version=self.version,
            )
        return ModelPrediction(text="", structured=None, model_version=self.version)


def _grounded_output(mode: str, prompt: str) -> Mapping[str, Any]:
    evidence = _evidence_records(prompt)
    if not evidence:
        return {}
    if mode == "recommendation":
        return _recommendations(evidence)
    if mode == "review_summary":
        return _review_summary(evidence)
    first = evidence[0]
    return {
        "response_type": "grounded_answer",
        "answer": f"{str(first['content']).rstrip('。！？!?；;.')} [E1]",
        "recommendations": [],
        "review_summary": None,
        "source_ids": ["E1"],
    }


def _recommendations(evidence: list[dict[str, Any]]) -> Mapping[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in evidence:
        metadata = record.get("metadata") or {}
        merchant_id = str(record.get("merchant_id") or metadata.get("merchant_id") or "").strip()
        if not merchant_id or merchant_id in seen:
            continue
        seen.add(merchant_id)
        source_id = str(record["id"])
        items.append(
            {
                "merchant_id": merchant_id,
                "name": str(metadata.get("merchant_name") or metadata.get("name") or merchant_id),
                "category": str(
                    metadata.get("category") or metadata.get("category_name") or "本地生活"
                ),
                "reason": str(record["content"]),
                "distance_meter": _number(metadata.get("distance_meter"), int),
                "avg_price_cent": _number(
                    metadata.get("avg_price_cent", metadata.get("price_cent")), int
                ),
                "rating": _number(metadata.get("rating"), float),
                "business_status": _business_status(metadata.get("business_status")),
                "data_updated_at": str(record.get("data_updated_at") or "未知"),
                "source_ids": [source_id],
                "tags": _tags(metadata.get("tags")),
            }
        )
        if len(items) == 5:
            break
    return {
        "response_type": "recommendation",
        "answer": "",
        "recommendations": items,
        "review_summary": None,
        "source_ids": [],
    }


def _review_summary(evidence: list[dict[str, Any]]) -> Mapping[str, Any]:
    first = evidence[0]
    metadata = first.get("metadata") or {}
    highlights: list[dict[str, Any]] = []
    drawbacks: list[dict[str, Any]] = []
    tags: list[str] = []
    for record in evidence[:5]:
        item_metadata = record.get("metadata") or {}
        item_tags = _tags(item_metadata.get("aspect_tags") or item_metadata.get("tags"))
        observation = {
            "text": str(record["content"]),
            "tags": item_tags,
            "source_ids": [str(record["id"])],
        }
        sentiment = str(item_metadata.get("sentiment") or "").casefold()
        if sentiment in {"negative", "neg", "负面", "消极"}:
            drawbacks.append(observation)
        else:
            highlights.append(observation)
        tags.extend(item_tags)
    return {
        "response_type": "review_summary",
        "answer": "",
        "recommendations": [],
        "review_summary": {
            "merchant_id": first.get("merchant_id"),
            "merchant_name": str(metadata.get("merchant_name") or metadata.get("name") or "该商家"),
            "highlights": highlights,
            "drawbacks": drawbacks,
            "recent_changes": [],
            "tags": list(dict.fromkeys(tags)),
            "data_updated_at": str(first.get("data_updated_at") or "未知"),
        },
        "source_ids": [],
    }


def _evidence_records(prompt: str) -> list[dict[str, Any]]:
    start = prompt.find('<evidence_set trust="untrusted_data_only">')
    end = prompt.find("</evidence_set>", start)
    if start < 0 or end < 0:
        return []
    body = prompt[prompt.find(">", start) + 1 : end]
    records: list[dict[str, Any]] = []
    for line in body.splitlines():
        try:
            value = json.loads(html.unescape(line.strip()))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict) and value.get("id") and value.get("content"):
            records.append(value)
    return records


def _number(value: object, cast: type[int] | type[float]) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _business_status(value: object) -> str | None:
    normalized = str(value).upper() if value is not None else ""
    return normalized if normalized in {"OPEN", "CLOSED", "UNKNOWN"} else None


def _tags(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if str(item).strip()][:12]
