"""Pydantic schemas for feedback and dataset APIs.

Implements request/response contracts defined in:
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.1 (feedback)
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.2 (datasets)
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Feedback schemas (POST /api/v1/chat/feedback)
# ---------------------------------------------------------------------------


class FeedbackCreate(BaseModel):
    """Request body for POST /api/v1/chat/feedback.

    Constraints (03-API接口规范.md §8.1):
    - rating ∈ {-1, 1}
    - correction max 4000 chars
    - Idempotent: one user one message = one active feedback
    """

    conversation_id: UUID
    message_id: UUID
    rating: Literal[-1, 1]
    correction: str | None = Field(default=None, max_length=4000)
    reason_codes: list[str] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    """Response for a feedback entry."""

    id: UUID
    user_id: UUID
    message_id: UUID
    conversation_id: UUID | None = None
    rating: int
    correction: str | None = None
    reason_codes: list[str] = []
    version: int
    review_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Dataset filter and create schemas
# ---------------------------------------------------------------------------


class DatasetFilter(BaseModel):
    """Filter conditions for dataset generation.

    Supports filtering by rating, time range, task type and review status
    per ST-501 acceptance criterion ③.
    """

    rating: Literal[-1, 1] | None = None
    task_type: str | None = None
    review_status: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class SplitConfig(BaseModel):
    """Train/validation/test split configuration.

    Supports entity (conversation) or session isolation per
    ST-501 acceptance criterion ⑥.
    """

    isolation_key: Literal["CONVERSATION", "ENTITY"] = "CONVERSATION"
    train_percent: float = Field(default=0.8, ge=0.0, le=1.0)
    validation_percent: float = Field(default=0.1, ge=0.0, le=1.0)
    test_percent: float = Field(default=0.1, ge=0.0, le=1.0)
    random_seed: int = Field(default=42, ge=0)


class DatasetCreateRequest(BaseModel):
    """Request body for POST /api/v1/fine-tuning/datasets."""

    name: str = Field(max_length=200)
    task_type: str = Field(max_length=64)
    filter: DatasetFilter = Field(default_factory=DatasetFilter)
    split_config: SplitConfig = Field(default_factory=SplitConfig)


class DatasetStatistics(BaseModel):
    """Label/source distribution within a dataset."""

    total_samples: int
    train_samples: int
    validation_samples: int
    test_samples: int
    label_distribution: dict[str, int] = {}
    source_distribution: dict[str, int] = {}


class DatasetResponse(BaseModel):
    """Response for GET /api/v1/fine-tuning/datasets/{id}.

    Per 03-API接口规范.md §8.2: returns data count, hash,
    redaction report and quality report.
    """

    id: UUID
    name: str
    task_type: str
    dataset_hash: str
    storage_uri: str
    sample_count: int
    status: str
    redaction_version: str
    statistics: DatasetStatistics
    quality_report_uri: str | None = None
    quality_report_hash: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Authorization rules
# ---------------------------------------------------------------------------

# Resource types for feedback/dataset authorization.
# Per 03-API接口规范.md §1.2 and 05-具体设计.md §10:
# - JWT + RBAC + resource scope
# - feedback: user can only submit/view own feedback
# - datasets: platform admin or model manager role required

FEEDBACK_PERMISSION = "feedback.create"
FEEDBACK_READ_PERMISSION = "feedback.read"
DATASET_CREATE_PERMISSION = "feedback.dataset.create"
DATASET_READ_PERMISSION = "feedback.dataset.read"

# Review status lifecycle for feedback
# Per 04-数据库约束说明.md §4.4: feedback can be in review pipeline
FEEDBACK_REVIEW_STATUSES = frozenset(
    {
        "PENDING_REVIEW",
        "APPROVED",
        "REJECTED",
    }
)

# Dataset status lifecycle
# Per 04-数据库约束说明.md §4.5: BUILDING → READY | REJECTED; READY → ARCHIVED
DATASET_STATUSES = frozenset(
    {
        "BUILDING",
        "READY",
        "REJECTED",
        "ARCHIVED",
    }
)

# Dataset split values
# Per 05-具体设计.md §9.2: train/validation/test split
DATASET_SPLITS = frozenset({"train", "validation", "test"})
