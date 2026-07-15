from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.core.readiness import run_readiness_checks

router = APIRouter(tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["alive"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["up", "down"]]


@router.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="alive")


@router.get("/health/ready", response_model=ReadyResponse)
async def ready(request: Request, response: Response) -> ReadyResponse:
    checks = await run_readiness_checks(
        request.app.state.readiness_checks,
        request.app.state.settings.dependency_timeout_seconds,
    )
    is_ready = all(result == "up" for result in checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ready" if is_ready else "not_ready", checks=checks)
