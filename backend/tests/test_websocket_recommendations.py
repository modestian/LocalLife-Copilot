from types import SimpleNamespace

from app.agents.generation import GroundedGeneration, GroundedOutput
from app.agents.types import ChatIntent, SourceCitation
from app.api.websocket_chat import _recommendation_event


def test_recommendation_event_exposes_structured_merchant_cards() -> None:
    output = GroundedOutput.model_validate(
        {
            "response_type": "recommendation",
            "answer": "",
            "recommendations": [
                {
                    "merchant_id": "merchant-green",
                    "name": "青禾小馆",
                    "category": "咖啡馆",
                    "reason": "环境安静并且有插座",
                    "avg_price_cent": 4800,
                    "rating": 4.6,
                    "business_status": "OPEN",
                    "data_updated_at": "2026-07-21T11:10:00Z",
                    "source_ids": ["E1"],
                    "tags": ["环境", "设施"],
                }
            ],
            "review_summary": None,
            "source_ids": [],
        }
    )
    source = SourceCitation(
        chunk_id="0190c4d2-7f20-7b31-9f75-8f6cc8e2b128",
        rank_no=1,
        source_location="merchant_reviews.csv#row=2",
        content_snapshot="环境安静并且有插座",
        score=0.91,
        evidence_id="E1",
    )
    result = SimpleNamespace(
        generation=GroundedGeneration(
            answer="青禾小馆",
            structured=output,
            sources=(source,),
            model_version="test-model",
        )
    )

    event = _recommendation_event(result, "request-1")

    assert event is not None
    assert event["type"] == "chat.recommendations"
    assert event["fallback"] == {"triggered": False}
    assert event["recommendations"] == [
        {
            "merchant_id": "merchant-green",
            "name": "青禾小馆",
            "category": "咖啡馆",
            "reason": "环境安静并且有插座",
            "distance_meter": None,
            "avg_price_cent": 4800,
            "rating": 4.6,
            "business_status": "OPEN",
            "data_updated_at": "2026-07-21T11:10:00Z",
            "source_chunk_ids": ["0190c4d2-7f20-7b31-9f75-8f6cc8e2b128"],
            "tags": ["环境", "设施"],
        }
    ]


def test_recommendation_event_exposes_grounded_fallback() -> None:
    result = SimpleNamespace(
        generation=GroundedGeneration(
            answer="当前资料不足",
            structured=None,
            sources=(),
            model_version=None,
            fallback_reason="no_evidence",
        )
    )

    event = _recommendation_event(result, "request-2")

    assert event == {
        "type": "chat.recommendations",
        "request_id": "request-2",
        "recommendations": [],
        "fallback": {"triggered": True, "reason": "no_evidence"},
    }


def test_recommendation_event_skips_general_chat_fallback() -> None:
    """general_chat 不涉及商家推荐，即使 generation 标记为 fallback 也不应发送兜底事件。"""
    result = SimpleNamespace(
        state={"intent": ChatIntent.GENERAL_CHAT},
        generation=GroundedGeneration(
            answer="你好！今天想聊点什么？",
            structured=None,
            sources=(),
            model_version="test-model",
            fallback_reason="general_chat",
        ),
    )

    event = _recommendation_event(result, "request-3")

    assert event is None
