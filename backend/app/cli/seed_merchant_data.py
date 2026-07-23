"""Generate rich merchant demo data: 20 merchants × 20 reviews each.

Idempotent: uses deterministic UUIDs and skips existing records.
Run:  python -m app.cli.seed_merchant_data
"""

import asyncio
import hashlib
import json
import random
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.infrastructure.db.models.operations import Merchant, Review
from app.infrastructure.db.models.sentiment import ReviewAnalysis

# ---------------------------------------------------------------------------
# Deterministic RNG
# ---------------------------------------------------------------------------
RNG = random.Random(20260717)

DEMO_TIME = datetime(2026, 7, 1, 9, 0, 0)
DEMO_TENANT_ID = UUID("70200000-0000-4000-8000-000000000001")
MODEL_VERSION = "demo-sentiment-v2"

# UUID bases
MERCHANT_BASE = 0x70200000_0000_4000_8000_000000000200
REVIEW_BASE = 0x70200000_0000_4000_8000_000000010000
ANALYSIS_BASE = 0x70200000_0000_4000_8000_000000020000


def _uuid(base: int, offset: int) -> UUID:
    return UUID(int=base + offset)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Aspect & reason codes (aligned with recommendation_generator / reply_generator)
# ---------------------------------------------------------------------------
ASPECT_CODES = [
    "taste",
    "portion",
    "price",
    "freshness",
    "appearance",
    "variety",
    "space",
    "quiet",
    "decoration",
    "hygiene",
    "location",
    "seating",
    "waiting_time",
    "attitude",
    "efficiency",
    "parking",
    "packing",
    "discount",
    "set_meal",
    "equipment",
    "overall",
]

NEGATIVE_REASON_CODES = [
    "taste_bad",
    "taste_unbalanced",
    "cold_food",
    "too_small",
    "stale",
    "spoiled",
    "overpriced",
    "false_discount",
    "dirty",
    "loud",
    "no_seat",
    "slow_wait",
    "rude_staff",
    "wrong_order",
    "no_parking",
    "bad_pack",
    "equipment_broken",
    "close_early",
    "delivery_delay",
]

# ---------------------------------------------------------------------------
# 20 Merchant definitions
# ---------------------------------------------------------------------------
MERCHANT_DEFS: list[dict] = [
    # --- Existing 2 (keep IDs consistent with seed_demo_data) ---
    {
        "name": "清河面馆",
        "category": "面馆",
        "address": "演示街区 1 号",
        "lng": 104.0668,
        "lat": 30.5728,
        "price": 4500,
        "rating": 4.6,
        "strengths": ["taste", "portion"],
        "weaknesses": ["waiting_time", "seating"],
        "neg_reasons": ["slow_wait", "no_seat"],
        "trend": "stable",
    },
    {
        "name": "书香咖啡馆",
        "category": "咖啡馆",
        "address": "演示街区 21 号",
        "lng": 104.0712,
        "lat": 30.5751,
        "price": 3800,
        "rating": 4.7,
        "strengths": ["quiet", "equipment"],
        "weaknesses": ["efficiency"],
        "neg_reasons": ["slow_wait"],
        "trend": "stable",
    },
    # --- New 18 ---
    {
        "name": "老灶火锅",
        "category": "火锅",
        "address": "锦江区春熙路 88 号",
        "lng": 104.0801,
        "lat": 30.6571,
        "price": 9800,
        "rating": 4.5,
        "strengths": ["taste", "variety"],
        "weaknesses": ["waiting_time", "loud"],
        "neg_reasons": ["slow_wait", "loud", "no_seat"],
        "trend": "improving",
    },
    {
        "name": "川味轩",
        "category": "川菜",
        "address": "青羊区宽窄巷子 12 号",
        "lng": 104.0555,
        "lat": 30.6699,
        "price": 6500,
        "rating": 4.3,
        "strengths": ["taste", "price"],
        "weaknesses": ["hygiene", "space"],
        "neg_reasons": ["dirty", "taste_unbalanced"],
        "trend": "declining",
    },
    {
        "name": "樱花日料",
        "category": "日料",
        "address": "武侯区天府大道 156 号",
        "lng": 104.0632,
        "lat": 30.5398,
        "price": 12800,
        "rating": 4.8,
        "strengths": ["freshness", "appearance", "attitude"],
        "weaknesses": ["price"],
        "neg_reasons": ["overpriced"],
        "trend": "stable",
    },
    {
        "name": "茶语时光",
        "category": "奶茶",
        "address": "成华区建设路 45 号",
        "lng": 104.1012,
        "lat": 30.6601,
        "price": 2200,
        "rating": 4.4,
        "strengths": ["taste", "appearance"],
        "weaknesses": ["efficiency"],
        "neg_reasons": ["slow_wait", "wrong_order"],
        "trend": "improving",
    },
    {
        "name": "炭火烧烤城",
        "category": "烧烤",
        "address": "金牛区交大路 77 号",
        "lng": 104.0421,
        "lat": 30.6812,
        "price": 7500,
        "rating": 4.1,
        "strengths": ["taste"],
        "weaknesses": ["hygiene", "loud"],
        "neg_reasons": ["dirty", "loud", "stale"],
        "trend": "declining",
    },
    {
        "name": "意面工坊",
        "category": "西餐",
        "address": "锦江区IFS 国际金融中心 B1",
        "lng": 104.0815,
        "lat": 30.6555,
        "price": 8800,
        "rating": 4.6,
        "strengths": ["taste", "decoration", "attitude"],
        "weaknesses": ["price"],
        "neg_reasons": ["overpriced", "slow_wait"],
        "trend": "stable",
    },
    {
        "name": "甜蜜物语",
        "category": "甜品",
        "address": "青羊区太古里 33 号",
        "lng": 104.0822,
        "lat": 30.6533,
        "price": 4200,
        "rating": 4.7,
        "strengths": ["appearance", "taste", "decoration"],
        "weaknesses": ["seating"],
        "neg_reasons": ["no_seat"],
        "trend": "stable",
    },
    {
        "name": "粤港茶餐厅",
        "category": "粤菜",
        "address": "武侯区人民南路 210 号",
        "lng": 104.0588,
        "lat": 30.5455,
        "price": 5800,
        "rating": 4.2,
        "strengths": ["taste", "variety"],
        "weaknesses": ["attitude", "efficiency"],
        "neg_reasons": ["rude_staff", "slow_wait"],
        "trend": "improving",
    },
    {
        "name": "鲜果捞",
        "category": "甜品",
        "address": "成华区万象城 L2-08",
        "lng": 104.1088,
        "lat": 30.6522,
        "price": 3500,
        "rating": 4.5,
        "strengths": ["freshness", "taste"],
        "weaknesses": ["portion"],
        "neg_reasons": ["too_small", "overpriced"],
        "trend": "stable",
    },
    {
        "name": "兰州拉面王",
        "category": "面馆",
        "address": "金牛区火车北站东路 5 号",
        "lng": 104.0701,
        "lat": 30.6901,
        "price": 2800,
        "rating": 4.0,
        "strengths": ["price", "taste"],
        "weaknesses": ["hygiene", "space"],
        "neg_reasons": ["dirty", "no_seat", "taste_bad"],
        "trend": "declining",
    },
    {
        "name": "海鲜大排档",
        "category": "海鲜",
        "address": "锦江区九眼桥西路 18 号",
        "lng": 104.0866,
        "lat": 30.6433,
        "price": 11000,
        "rating": 4.3,
        "strengths": ["freshness", "variety"],
        "weaknesses": ["price", "hygiene"],
        "neg_reasons": ["overpriced", "stale", "dirty"],
        "trend": "stable",
    },
    {
        "name": "素心素食",
        "category": "素食",
        "address": "青羊区文殊院街 9 号",
        "lng": 104.0611,
        "lat": 30.6755,
        "price": 5200,
        "rating": 4.6,
        "strengths": ["hygiene", "quiet", "taste"],
        "weaknesses": ["variety"],
        "neg_reasons": ["taste_unbalanced"],
        "trend": "stable",
    },
    {
        "name": "烤匠",
        "category": "烧烤",
        "address": "武侯区玉林路 66 号",
        "lng": 104.0522,
        "lat": 30.5566,
        "price": 8200,
        "rating": 4.4,
        "strengths": ["taste", "attitude"],
        "weaknesses": ["waiting_time", "loud"],
        "neg_reasons": ["slow_wait", "loud"],
        "trend": "improving",
    },
    {
        "name": "小笼包之家",
        "category": "小吃",
        "address": "成华区双桥路 120 号",
        "lng": 104.0955,
        "lat": 30.6688,
        "price": 3200,
        "rating": 4.5,
        "strengths": ["taste", "price", "portion"],
        "weaknesses": ["space"],
        "neg_reasons": ["no_seat", "dirty"],
        "trend": "stable",
    },
    {
        "name": "韩宫烤肉",
        "category": "韩餐",
        "address": "锦江区红星路三段 99 号",
        "lng": 104.0799,
        "lat": 30.6511,
        "price": 10500,
        "rating": 4.2,
        "strengths": ["taste", "equipment"],
        "weaknesses": ["price", "efficiency"],
        "neg_reasons": ["overpriced", "slow_wait", "equipment_broken"],
        "trend": "declining",
    },
    {
        "name": "云南米线坊",
        "category": "米线",
        "address": "青羊区光华村街 38 号",
        "lng": 104.0344,
        "lat": 30.6622,
        "price": 3000,
        "rating": 4.3,
        "strengths": ["taste", "price"],
        "weaknesses": ["attitude"],
        "neg_reasons": ["rude_staff", "taste_unbalanced"],
        "trend": "stable",
    },
    {
        "name": "披萨星球",
        "category": "西餐",
        "address": "武侯区天府三街 188 号",
        "lng": 104.0611,
        "lat": 30.5311,
        "price": 7800,
        "rating": 4.1,
        "strengths": ["variety", "space"],
        "weaknesses": ["taste", "efficiency"],
        "neg_reasons": ["taste_bad", "delivery_delay", "cold_food"],
        "trend": "declining",
    },
    {
        "name": "鲜茶道",
        "category": "奶茶",
        "address": "成华区建设巷 22 号",
        "lng": 104.1033,
        "lat": 30.6633,
        "price": 1800,
        "rating": 4.6,
        "strengths": ["taste", "price", "attitude"],
        "weaknesses": ["packing"],
        "neg_reasons": ["bad_pack"],
        "trend": "improving",
    },
    {
        "name": "老成都串串香",
        "category": "串串",
        "address": "金牛区抚琴西路 55 号",
        "lng": 104.0455,
        "lat": 30.6722,
        "price": 6800,
        "rating": 4.4,
        "strengths": ["taste", "variety", "price"],
        "weaknesses": ["hygiene", "waiting_time"],
        "neg_reasons": ["dirty", "slow_wait", "stale"],
        "trend": "stable",
    },
]

# ---------------------------------------------------------------------------
# Review text templates per sentiment
# ---------------------------------------------------------------------------
POSITIVE_TEMPLATES = [
    "这家店的{aspect}真的很棒，下次还会再来！",
    "非常满意，{aspect}超出预期，推荐给大家。",
    "朋友推荐来的，果然没失望，{aspect}很赞。",
    "五星好评！{aspect}让人印象深刻，值得回头。",
    "每次来都很满意，特别是{aspect}方面做得很好。",
    "环境舒适，{aspect}一流，会常来光顾。",
    "性价比很高，{aspect}都不错，适合朋友聚餐。",
    "服务周到，{aspect}令人满意，整体体验很好。",
    "味道正宗，{aspect}很到位，是正宗的好店。",
    "来了好几次了，{aspect}一直很稳定，信赖这家店。",
]

NEUTRAL_TEMPLATES = [
    "整体一般般吧，{aspect}中规中矩，不算惊艳。",
    "还行吧，{aspect}没什么特别的，但也不差。",
    "路过随便吃吃，{aspect}普通，不会特意再来。",
    "价格适中，{aspect}一般，可以随便吃一顿。",
    "没有网上说的那么好，{aspect}也就那样吧。",
    "凑合能吃，{aspect}不算突出，填个肚子还行。",
]

NEGATIVE_TEMPLATES = [
    "太失望了，{reason_text}，体验很差。",
    "不会再来了，{reason_text}让人无法接受。",
    "等了好久，{reason_text}，非常不满意。",
    "朋友聚餐选了这里，结果{reason_text}，很尴尬。",
    "差评！{reason_text}，希望店家能改进。",
    "第一次来就踩雷，{reason_text}，不推荐。",
    "本来很期待，结果{reason_text}，太可惜了。",
]

REASON_TEXT_MAP = {
    "taste_bad": "菜品味道太差",
    "taste_unbalanced": "口味忽咸忽淡不稳定",
    "cold_food": "菜上来都是凉的",
    "too_small": "分量太少了",
    "stale": "食材明显不新鲜",
    "spoiled": "食物有变质味道",
    "overpriced": "价格虚高不值这个价",
    "false_discount": "优惠活动是虚假宣传",
    "dirty": "卫生条件太差",
    "loud": "环境太吵了",
    "no_seat": "去了根本没座位",
    "slow_wait": "等了快一个小时",
    "rude_staff": "服务员态度恶劣",
    "wrong_order": "上错菜了还不承认",
    "no_parking": "停车太难了",
    "bad_pack": "外卖包装一塌糊涂",
    "equipment_broken": "店里设备坏了没人修",
    "close_early": "没到时间就关门了",
    "delivery_delay": "外卖超时一个多小时",
}

ASPECT_CN = {
    "taste": "口味",
    "portion": "分量",
    "price": "性价比",
    "freshness": "新鲜度",
    "appearance": "卖相",
    "variety": "品种",
    "space": "空间",
    "quiet": "安静程度",
    "decoration": "装修",
    "hygiene": "卫生",
    "location": "位置",
    "seating": "座位",
    "waiting_time": "出餐速度",
    "attitude": "服务态度",
    "efficiency": "效率",
    "parking": "停车",
    "packing": "打包",
    "discount": "优惠",
    "set_meal": "套餐",
    "equipment": "设施",
    "overall": "整体体验",
}


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------


def _generate_reviews_for_merchant(merchant_idx: int, mdef: dict) -> list[dict]:
    """Generate 20 reviews for one merchant with deterministic randomness."""
    rng = random.Random(20260717 + merchant_idx * 100)
    reviews = []

    # Sentiment distribution based on trend
    trend = mdef["trend"]
    if trend == "improving":
        # Earlier reviews more negative, later more positive
        sentiments = ["NEGATIVE"] * 5 + ["NEUTRAL"] * 4 + ["POSITIVE"] * 11
    elif trend == "declining":
        sentiments = ["POSITIVE"] * 5 + ["NEUTRAL"] * 4 + ["NEGATIVE"] * 11
    else:
        sentiments = ["POSITIVE"] * 12 + ["NEUTRAL"] * 4 + ["NEGATIVE"] * 4

    rng.shuffle(sentiments)

    # Spread dates over 3 months: 2026-04-01 to 2026-06-30
    start_date = datetime(2026, 4, 1)
    date_range_days = 90

    for i in range(20):
        sentiment = sentiments[i]
        day_offset = int(i * date_range_days / 20) + rng.randint(0, 3)
        review_date = start_date + timedelta(days=day_offset, hours=rng.randint(10, 21))

        if sentiment == "POSITIVE":
            aspect = rng.choice(mdef["strengths"])
            aspect_cn = ASPECT_CN.get(aspect, aspect)
            template = rng.choice(POSITIVE_TEMPLATES)
            text = template.format(aspect=aspect_cn)
            aspects = [aspect]
            if rng.random() > 0.5 and len(mdef["strengths"]) > 1:
                extra = rng.choice([a for a in mdef["strengths"] if a != aspect])
                aspects.append(extra)
            reasons = []
            confidence = round(rng.uniform(0.92, 0.99), 2)
            rating = round(rng.uniform(4.0, 5.0), 1)
        elif sentiment == "NEUTRAL":
            aspect = rng.choice(mdef["strengths"] + mdef["weaknesses"])
            aspect_cn = ASPECT_CN.get(aspect, aspect)
            template = rng.choice(NEUTRAL_TEMPLATES)
            text = template.format(aspect=aspect_cn)
            aspects = [aspect]
            reasons = []
            confidence = round(rng.uniform(0.80, 0.90), 2)
            rating = round(rng.uniform(2.5, 3.5), 1)
        else:  # NEGATIVE
            reason = rng.choice(mdef["neg_reasons"])
            reason_text = REASON_TEXT_MAP.get(reason, "体验不好")
            template = rng.choice(NEGATIVE_TEMPLATES)
            text = template.format(reason_text=reason_text)
            # Map reason to aspect
            reason_to_aspect = {
                "taste_bad": "taste",
                "taste_unbalanced": "taste",
                "cold_food": "overall",
                "too_small": "portion",
                "stale": "freshness",
                "spoiled": "freshness",
                "overpriced": "price",
                "false_discount": "discount",
                "dirty": "hygiene",
                "loud": "quiet",
                "no_seat": "seating",
                "slow_wait": "waiting_time",
                "rude_staff": "attitude",
                "wrong_order": "efficiency",
                "no_parking": "parking",
                "bad_pack": "packing",
                "equipment_broken": "equipment",
                "close_early": "overall",
                "delivery_delay": "efficiency",
            }
            aspects = [reason_to_aspect.get(reason, "overall")]
            reasons = [reason]
            confidence = round(rng.uniform(0.88, 0.97), 2)
            rating = round(rng.uniform(1.0, 2.5), 1)

        reviews.append(
            {
                "text": text,
                "sentiment": sentiment,
                "confidence": confidence,
                "aspects": aspects,
                "reasons": reasons,
                "date": review_date,
                "rating": rating,
                "author": f"食客_{merchant_idx + 1:02d}_{i + 1:02d}",
            }
        )

    return reviews


# ---------------------------------------------------------------------------
# Database seeding
# ---------------------------------------------------------------------------


async def _add_if_missing(session: AsyncSession, record: object) -> bool:
    record_id = getattr(record, "id", None)
    if record_id is None:
        raise ValueError(f"{type(record).__name__} must expose an id")
    if await session.get(type(record), record_id) is not None:
        return False
    session.add(record)
    return True


async def seed_merchant_data(session: AsyncSession) -> dict[str, int]:
    """Insert 20 merchants × 20 reviews into the database (idempotent)."""
    merchant_count = 0
    review_count = 0
    analysis_count = 0

    for m_idx, mdef in enumerate(MERCHANT_DEFS):
        merchant_id = _uuid(MERCHANT_BASE, m_idx)

        # Skip first 2 if they already exist (seeded by seed_demo_data)
        if m_idx < 2:
            existing = await session.get(Merchant, merchant_id)
            if existing is not None:
                merchant_count += 1
                # Still seed reviews if missing
            else:
                # Use the original IDs from seed_demo_data
                if m_idx == 0:
                    merchant_id = UUID("70200000-0000-4000-8000-000000000020")
                else:
                    merchant_id = UUID("70200000-0000-4000-8000-000000000021")
                await _add_if_missing(
                    session,
                    Merchant(
                        id=merchant_id,
                        region_id=DEMO_TENANT_ID,
                        category=mdef["category"],
                        name=mdef["name"],
                        normalized_name=mdef["name"],
                        address=mdef["address"],
                        longitude=mdef["lng"],
                        latitude=mdef["lat"],
                        avg_price_cent=mdef["price"],
                        rating=mdef["rating"],
                        business_status="OPEN",
                        last_verified_at=DEMO_TIME,
                        created_at=DEMO_TIME,
                        updated_at=DEMO_TIME,
                    ),
                )
                merchant_count += 1
        else:
            added = await _add_if_missing(
                session,
                Merchant(
                    id=merchant_id,
                    region_id=DEMO_TENANT_ID,
                    category=mdef["category"],
                    name=mdef["name"],
                    normalized_name=mdef["name"],
                    address=mdef["address"],
                    longitude=mdef["lng"],
                    latitude=mdef["lat"],
                    avg_price_cent=mdef["price"],
                    rating=mdef["rating"],
                    business_hours_json={"mon_sun": "10:00-22:00"},
                    business_status="OPEN",
                    last_verified_at=DEMO_TIME,
                    created_at=DEMO_TIME,
                    updated_at=DEMO_TIME,
                ),
            )
            if added:
                merchant_count += 1

        # Generate reviews for this merchant
        reviews = _generate_reviews_for_merchant(m_idx, mdef)
        merchant_id_str = str(merchant_id)

        for r_idx, rev in enumerate(reviews):
            review_id = _uuid(REVIEW_BASE, m_idx * 20 + r_idx)
            analysis_id = _uuid(ANALYSIS_BASE, m_idx * 20 + r_idx)

            # Review record
            await _add_if_missing(
                session,
                Review(
                    id=review_id,
                    merchant_id=merchant_id,
                    author_ref=rev["author"],
                    content=rev["text"],
                    content_hash=_sha256(rev["text"]),
                    rating=rev["rating"],
                    reviewed_at=rev["date"],
                    source_type="DEMO",
                    source_review_id=f"demo-{m_idx:02d}-{r_idx:02d}",
                    status="PUBLISHED",
                    tags_json=[ASPECT_CN.get(a, a) for a in rev["aspects"]],
                    created_at=DEMO_TIME,
                    updated_at=DEMO_TIME,
                ),
            )
            review_count += 1

            # ReviewAnalysis record
            await _add_if_missing(
                session,
                ReviewAnalysis(
                    id=analysis_id,
                    merchant_id=merchant_id_str,
                    review_text=rev["text"],
                    sentiment=rev["sentiment"],
                    confidence=rev["confidence"],
                    model_version=MODEL_VERSION,
                    aspect_labels=json.dumps(rev["aspects"], ensure_ascii=False),
                    negative_reasons=json.dumps(rev["reasons"], ensure_ascii=False),
                    review_date=rev["date"],
                    created_at=DEMO_TIME,
                    updated_at=DEMO_TIME,
                ),
            )
            analysis_count += 1

    return {
        "merchants": merchant_count,
        "reviews": review_count,
        "analyses": analysis_count,
    }


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


async def _run() -> dict[str, int]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with AsyncSession(engine) as session, session.begin():
            return await seed_merchant_data(session)
    finally:
        await engine.dispose()


def main() -> None:
    summary = asyncio.run(_run())
    print(
        f"Merchant demo data ready: "
        f"{summary['merchants']} merchants, "
        f"{summary['reviews']} reviews, "
        f"{summary['analyses']} review analyses."
    )


if __name__ == "__main__":
    main()
