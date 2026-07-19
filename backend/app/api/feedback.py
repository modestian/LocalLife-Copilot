"""Feedback REST endpoints.

Implements the endpoints defined in:
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.1

POST /api/v1/chat/feedback — submit or update feedback (idempotent).
GET  /api/v1/chat/feedback    — query feedbacks with quality filters.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.feedback import (
    ConversationMismatchError,
    FeedbackService,
    InvalidMessageReferenceError,
    MissingModelError,
    NegativeFeedbackContentError,
)
from app.core.api import success_response
from app.core.errors import AppError
from app.domain.feedback import (
    DatasetFilter,
    FeedbackCreate,
    FeedbackResponse,
)

router = APIRouter(prefix="/chat", tags=["feedback"])


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_feedback_service(request: Request) -> FeedbackService:
    service: FeedbackService | None = getattr(request.app.state, "feedback_service", None)
    if service is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "反馈服务尚未配置")
    return service


FeedbackServiceDependency = Annotated[FeedbackService, Depends(get_feedback_service)]


# ---------------------------------------------------------------------------
# Query-parameter types
# ---------------------------------------------------------------------------

_RatingParam = Annotated[int | None, Query(ge=-1, le=1)]
_TaskTypeParam = Annotated[str | None, Query(max_length=64)]
_ReviewStatusParam = Annotated[str | None, Query(max_length=20)]
_DateParam = Annotated[str | None, Query()]


# ---------------------------------------------------------------------------
# POST /api/v1/chat/feedback
# ---------------------------------------------------------------------------


@router.post("/feedback")
async def submit_feedback(
    request: Request,
    payload: FeedbackCreate,
    principal: CurrentPrincipal,
    service: FeedbackServiceDependency,
) -> dict[str, Any]:
    """Submit or update feedback for a chat message.

    Per §8.1: rating ∈ {-1, 1}; one user × one message = one active
    feedback; repeated submissions increment version and preserve audit.
    """
    try:
        record = await service.submit_feedback(principal.user_id, payload)
    except InvalidMessageReferenceError as exc:
        raise AppError(404, "FEEDBACK_MESSAGE_NOT_FOUND", str(exc)) from exc
    except ConversationMismatchError as exc:
        raise AppError(422, "FEEDBACK_CONVERSATION_MISMATCH", str(exc)) from exc
    except MissingModelError as exc:
        raise AppError(422, "FEEDBACK_MISSING_MODEL_VERSION", str(exc)) from exc
    except NegativeFeedbackContentError as exc:
        raise AppError(422, "FEEDBACK_NEGATIVE_CONTENT_REQUIRED", str(exc)) from exc

    response = FeedbackResponse(
        id=record.id,
        user_id=record.user_id,
        message_id=record.message_id,
        conversation_id=None,
        rating=record.rating,
        correction=record.correction,
        reason_codes=record.reason_codes,
        version=record.version,
        review_status=record.review_status,
        created_at=record.created_at,  # type: ignore[arg-type]
        updated_at=record.updated_at,  # type: ignore[arg-type]
    )
    return success_response(request, response.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# GET /api/v1/chat/feedback
# ---------------------------------------------------------------------------


@router.get("/feedback")
async def query_feedbacks(
    request: Request,
    principal: CurrentPrincipal,
    service: FeedbackServiceDependency,
    rating: _RatingParam = None,
    task_type: _TaskTypeParam = None,
    review_status: _ReviewStatusParam = None,
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Query feedback entries with quality filters.

    Per ST-501 criterion ③: supports filtering by rating, time range,
    task type and review status.
    """
    from datetime import datetime as _dt

    parsed_start = _dt.fromisoformat(start_date) if start_date else None
    parsed_end = _dt.fromisoformat(end_date) if end_date else None

    filter_obj = DatasetFilter(
        rating=rating,
        task_type=task_type,
        review_status=review_status,
        start_date=parsed_start,
        end_date=parsed_end,
    )
    records = await service.query_feedbacks(filter_obj)
    items = [
        FeedbackResponse(
            id=fb.id,
            user_id=fb.user_id,
            message_id=fb.message_id,
            conversation_id=None,
            rating=fb.rating,
            correction=fb.correction,
            reason_codes=fb.reason_codes,
            version=fb.version,
            review_status=fb.review_status,
            created_at=fb.created_at,  # type: ignore[arg-type]
            updated_at=fb.updated_at,  # type: ignore[arg-type]
        ).model_dump(mode="json")
        for fb in records
    ]
    return success_response(request, items)
