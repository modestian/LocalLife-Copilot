from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from app.cli.seed_demo_data import DEMO_USERS
from app.etl.loaders import loader_for
from app.etl.merchant_reviews import (
    MerchantReviewImportError,
    enrich_source_record,
    parse_merchant_review_rows,
)
from app.etl.models import CleanStatus, DocumentRecord

TENANT_ID = UUID("70200000-0000-4000-8000-000000000001")


def record(row: int, **overrides: object) -> DocumentRecord:
    values: dict[str, object] = {
        "merchant_key": "hotpot-001",
        "merchant_name": "老灶火锅",
        "category": "火锅",
        "address": "锦江区春熙路88号",
        "longitude": 104.0801,
        "latitude": 30.6571,
        "avg_price_cent": 9800,
        "merchant_rating": 4.5,
        "business_status": "OPEN",
        "review_key": f"review-{row}",
        "review_content": "锅底香辣，牛肉很新鲜",
        "review_rating": 5,
        "reviewed_at": "2026-07-20T12:30:00+08:00",
        "author_ref": "user-a",
        "tags": "味道|新鲜",
        "owner_username": "demo-merchant",
    }
    values.update(overrides)
    content = str(values)
    return DocumentRecord(
        content=content,
        metadata={"row": row, "row_data": values},
        source_key=f"merchant.csv#row={row}",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        clean_status=CleanStatus.CLEANED,
    )


def test_contract_parses_rows_and_enriches_retrieval_metadata() -> None:
    rows = parse_merchant_review_rows(TENANT_ID, (record(2), record(3)))

    assert len(rows) == 2
    assert rows[0].merchant_id == rows[1].merchant_id
    assert rows[0].reviewed_at == datetime(2026, 7, 20, 4, 30)
    assert rows[0].tags == ("味道", "新鲜")

    enriched = enrich_source_record(rows[0])
    assert enriched.metadata["merchant_id"] == str(rows[0].merchant_id)
    assert enriched.metadata["merchant_name"] == "老灶火锅"
    assert enriched.metadata["category_ids"] == ["火锅"]
    assert enriched.metadata["avg_price_cent"] == 9800
    assert enriched.metadata["price_cent"] == 9800
    assert enriched.metadata["rating"] == 4.5
    assert enriched.metadata["review_date"] == "2026-07-20T04:30:00"
    assert enriched.metadata["last_verified_at"] == "2026-07-20T04:30:00"
    assert enriched.metadata["tags"] == list(rows[0].tags)
    assert enriched.metadata["location"] == {"lat": 30.6571, "lon": 104.0801}


def test_demo_xlsx_references_an_existing_demo_owner() -> None:
    path = Path(__file__).parents[1] / "demo_data" / "merchant_knowledge_excel.xlsx"
    with path.open("rb") as source:
        records = tuple(loader_for(path.name).load(source, source_key=path.name))

    rows = parse_merchant_review_rows(TENANT_ID, records)
    owners = {row.owner_username for row in rows if row.owner_username is not None}
    seeded_usernames = {user.username for user in DEMO_USERS}

    assert len(rows) == 9
    assert owners == {"demo-merchant"}
    assert owners <= seeded_usernames


def test_contract_rejects_missing_required_columns() -> None:
    with pytest.raises(MerchantReviewImportError, match="review_content"):
        parse_merchant_review_rows(TENANT_ID, (record(2, review_content=""),))


def test_contract_rejects_conflicting_merchant_master_data() -> None:
    with pytest.raises(MerchantReviewImportError, match="主数据在文件内不一致"):
        parse_merchant_review_rows(
            TENANT_ID,
            (record(2), record(3, address="另一个地址")),
        )


def test_contract_rejects_duplicate_review_keys() -> None:
    with pytest.raises(MerchantReviewImportError, match="评论键重复"):
        parse_merchant_review_rows(
            TENANT_ID,
            (record(2, review_key="same"), record(3, review_key="same")),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("longitude", 181, "longitude"),
        ("latitude", -91, "latitude"),
        ("review_rating", 6, "review_rating"),
        ("avg_price_cent", 1.5, "必须是整数"),
        ("business_status", "BUSY", "business_status"),
        ("reviewed_at", "not-a-time", "ISO 8601"),
    ],
)
def test_contract_rejects_invalid_values(field: str, value: object, message: str) -> None:
    with pytest.raises(MerchantReviewImportError, match=message):
        parse_merchant_review_rows(TENANT_ID, (record(2, **{field: value}),))


# ---------------------------------------------------------------------------
# Additional parsing error paths (previously uncovered)
# ---------------------------------------------------------------------------


def test_contract_rejects_empty_records() -> None:
    with pytest.raises(MerchantReviewImportError, match="没有可导入的数据行"):
        parse_merchant_review_rows(TENANT_ID, ())


def test_contract_rejects_non_dict_row_data() -> None:
    doc = DocumentRecord(
        content="test",
        metadata={"row_data": "not-a-dict"},
        source_key="test.csv#row=1",
        content_hash="a" * 64,
        clean_status=CleanStatus.CLEANED,
    )
    with pytest.raises(MerchantReviewImportError, match="不是结构化行"):
        parse_merchant_review_rows(TENANT_ID, (doc,))


def test_contract_rejects_text_too_long() -> None:
    with pytest.raises(MerchantReviewImportError, match="merchant_name"):
        parse_merchant_review_rows(TENANT_ID, (record(2, merchant_name="x" * 201),))


def test_contract_rejects_non_numeric_decimal() -> None:
    with pytest.raises(MerchantReviewImportError, match="必须是数字"):
        parse_merchant_review_rows(TENANT_ID, (record(2, longitude="abc"),))


def test_optional_int_returns_none_for_blank() -> None:
    rows = parse_merchant_review_rows(TENANT_ID, (record(2, avg_price_cent=""),))
    assert rows[0].avg_price_cent is None


def test_contract_rejects_too_many_tags() -> None:
    with pytest.raises(MerchantReviewImportError, match="tags"):
        many_tags = ",".join(str(i) for i in range(21))
        parse_merchant_review_rows(TENANT_ID, (record(2, tags=many_tags),))


def test_contract_rejects_tag_too_long() -> None:
    with pytest.raises(MerchantReviewImportError, match="tags"):
        parse_merchant_review_rows(TENANT_ID, (record(2, tags="x" * 65),))
