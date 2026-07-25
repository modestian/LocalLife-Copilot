"""Validated merchant-review import contract for structured knowledge files."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID, uuid5

from app.etl.models import DocumentRecord, JsonValue

# Reference point for distance calculation (春熙路, Chengdu)
_REF_LON: float = 104.08
_REF_LAT: float = 30.66

MERCHANT_IMPORT_NAMESPACE = UUID("70200000-0000-4000-8000-00000000a001")
REQUIRED_COLUMNS = frozenset(
    {
        "merchant_key",
        "merchant_name",
        "category",
        "address",
        "longitude",
        "latitude",
        "review_key",
        "review_content",
        "review_rating",
        "reviewed_at",
    }
)
BUSINESS_STATUSES = frozenset({"OPEN", "CLOSED", "SUSPENDED", "UNKNOWN"})


class MerchantReviewImportError(ValueError):
    """A merchant-review file violates its documented import contract."""


@dataclass(frozen=True, slots=True)
class MerchantReviewRow:
    source_record: DocumentRecord
    merchant_id: UUID
    merchant_key: str
    merchant_name: str
    category: str
    address: str
    longitude: Decimal
    latitude: Decimal
    avg_price_cent: int | None
    merchant_rating: Decimal
    business_status: str
    review_key: str
    review_content: str
    review_rating: Decimal
    reviewed_at: datetime
    author_ref: str | None
    tags: tuple[str, ...]
    owner_username: str | None


@dataclass(frozen=True, slots=True)
class MerchantReviewImportResult:
    records: tuple[DocumentRecord, ...]
    merchant_count: int
    review_count: int
    analysis_task_ids: tuple[UUID, ...] = ()

    def summary(self) -> dict[str, JsonValue]:
        return {
            "type": "merchant_reviews",
            "merchant_count": self.merchant_count,
            "review_count": self.review_count,
            "analysis_task_ids": [str(value) for value in self.analysis_task_ids],
        }


class MerchantReviewImporter(Protocol):
    def import_records(
        self, tenant_id: UUID, records: tuple[DocumentRecord, ...]
    ) -> MerchantReviewImportResult: ...


def parse_merchant_review_rows(
    tenant_id: UUID, records: tuple[DocumentRecord, ...]
) -> tuple[MerchantReviewRow, ...]:
    if not records:
        raise MerchantReviewImportError("商家评论文件没有可导入的数据行")

    rows = tuple(_parse_row(tenant_id, record) for record in records)
    canonical: dict[str, tuple[object, ...]] = {}
    review_keys: set[tuple[str, str]] = set()
    for row in rows:
        merchant_values = (
            row.merchant_name,
            row.category,
            row.address,
            row.longitude,
            row.latitude,
            row.avg_price_cent,
            row.merchant_rating,
            row.business_status,
            row.owner_username,
        )
        previous = canonical.setdefault(row.merchant_key, merchant_values)
        if previous != merchant_values:
            raise MerchantReviewImportError(
                f"merchant_key={row.merchant_key!r} 的商家主数据在文件内不一致"
            )
        review_identity = (row.merchant_key, row.review_key)
        if review_identity in review_keys:
            raise MerchantReviewImportError(
                f"评论键重复：merchant_key={row.merchant_key!r}, review_key={row.review_key!r}"
            )
        review_keys.add(review_identity)
    return rows


def enrich_source_record(row: MerchantReviewRow) -> DocumentRecord:
    metadata = {
        **row.source_record.metadata,
        "merchant_id": str(row.merchant_id),
        "merchant_name": row.merchant_name,
        "category": row.category,
        "category_ids": [row.category],
        "business_status": row.business_status,
        "avg_price_cent": row.avg_price_cent,
        "price_cent": row.avg_price_cent,
        "rating": float(row.merchant_rating),
        "distance_meter": _haversine_distance(
            float(row.longitude), float(row.latitude), _REF_LON, _REF_LAT
        ),
        "review_date": row.reviewed_at.isoformat(),
        "last_verified_at": row.reviewed_at.isoformat(),
        "tags": list(row.tags),
        "location": {"lat": float(row.latitude), "lon": float(row.longitude)},
        "source_type": "merchant_review_import",
        "source_location": row.source_record.source_key,
    }
    return replace(row.source_record, metadata=metadata)


def _parse_row(tenant_id: UUID, record: DocumentRecord) -> MerchantReviewRow:
    raw = record.metadata.get("row_data")
    if not isinstance(raw, dict):
        raise MerchantReviewImportError(
            f"{record.source_key} 不是结构化行；商家评论导入仅支持 CSV/XLSX"
        )
    values = {str(key).strip(): value for key, value in raw.items()}
    missing = sorted(column for column in REQUIRED_COLUMNS if _blank(values.get(column)))
    if missing:
        raise MerchantReviewImportError(f"{record.source_key} 缺少必填字段：{', '.join(missing)}")

    merchant_key = _text(values["merchant_key"], "merchant_key", 64, record)
    merchant_id = uuid5(MERCHANT_IMPORT_NAMESPACE, f"{tenant_id}:{merchant_key}")
    return MerchantReviewRow(
        source_record=record,
        merchant_id=merchant_id,
        merchant_key=merchant_key,
        merchant_name=_text(values["merchant_name"], "merchant_name", 200, record),
        category=_text(values["category"], "category", 128, record),
        address=_text(values["address"], "address", 500, record),
        longitude=_decimal(values["longitude"], "longitude", -180, 180, record),
        latitude=_decimal(values["latitude"], "latitude", -90, 90, record),
        avg_price_cent=_optional_int(values.get("avg_price_cent"), "avg_price_cent", record),
        merchant_rating=_decimal(values.get("merchant_rating", 0), "merchant_rating", 0, 5, record),
        business_status=_status(values.get("business_status"), record),
        review_key=_text(values["review_key"], "review_key", 64, record),
        review_content=_text(values["review_content"], "review_content", 100_000, record),
        review_rating=_decimal(values["review_rating"], "review_rating", 0, 5, record),
        reviewed_at=_datetime(values["reviewed_at"], record),
        author_ref=_optional_text(values.get("author_ref"), "author_ref", 128, record),
        tags=_tags(values.get("tags"), record),
        owner_username=_optional_text(values.get("owner_username"), "owner_username", 64, record),
    )


def _text(value: object, field: str, maximum: int, record: DocumentRecord) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum:
        raise MerchantReviewImportError(f"{record.source_key} 的 {field} 必须为 1–{maximum} 个字符")
    return text


def _optional_text(value: object, field: str, maximum: int, record: DocumentRecord) -> str | None:
    if _blank(value):
        return None
    return _text(value, field, maximum, record)


def _decimal(
    value: object,
    field: str,
    minimum: int,
    maximum: int,
    record: DocumentRecord,
) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise MerchantReviewImportError(f"{record.source_key} 的 {field} 必须是数字") from exc
    if not parsed.is_finite() or not minimum <= parsed <= maximum:
        raise MerchantReviewImportError(
            f"{record.source_key} 的 {field} 必须在 {minimum}–{maximum} 之间"
        )
    return parsed


def _optional_int(value: object, field: str, record: DocumentRecord) -> int | None:
    if _blank(value):
        return None
    parsed = _decimal(value, field, 0, 2**63 - 1, record)
    if parsed != parsed.to_integral_value():
        raise MerchantReviewImportError(f"{record.source_key} 的 {field} 必须是整数")
    return int(parsed)


def _datetime(value: object, record: DocumentRecord) -> datetime:
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MerchantReviewImportError(
            f"{record.source_key} 的 reviewed_at 必须是 ISO 8601 时间"
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _status(value: object, record: DocumentRecord) -> str:
    status = "UNKNOWN" if _blank(value) else str(value).strip().upper()
    if status not in BUSINESS_STATUSES:
        raise MerchantReviewImportError(
            f"{record.source_key} 的 business_status 必须是 "
            f"{', '.join(sorted(BUSINESS_STATUSES))} 之一"
        )
    return status


def _tags(value: object, record: DocumentRecord) -> tuple[str, ...]:
    if _blank(value):
        return ()
    normalized = str(value).replace("|", ",")
    tags = tuple(dict.fromkeys(item.strip() for item in normalized.split(",") if item.strip()))
    if any(len(tag) > 64 for tag in tags) or len(tags) > 20:
        raise MerchantReviewImportError(f"{record.source_key} 的 tags 最多20项且单项不超过64字符")
    return tags


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> int:
    """Compute distance in meters between two (lon, lat) pairs."""
    r = 6_371_000  # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return round(r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
