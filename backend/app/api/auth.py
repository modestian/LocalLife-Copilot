from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.auth import AuthenticationError, AuthService, TokenPair
from app.application.login_rate_limit import LoginRateLimiter, login_rate_limit_subject
from app.core.api import success_response
from app.core.errors import AppError

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


class WebSocketTokenResponse(BaseModel):
    ws_token: str
    expires_in: int


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/login")
async def login(
    payload: LoginRequest, request: Request, service: AuthServiceDependency
) -> dict[str, Any]:
    limiter: LoginRateLimiter = request.app.state.login_rate_limiter
    client_ip = request.client.host if request.client is not None else "unknown"
    subject = login_rate_limit_subject(payload.username, client_ip)
    limit = await limiter.status(subject)
    if limit.blocked:
        raise _rate_limit_error(limit.retry_after_seconds)
    try:
        pair = await service.login(payload.username, payload.password)
    except AuthenticationError as exc:
        limit = await limiter.record_failure(subject)
        if limit.blocked:
            raise _rate_limit_error(limit.retry_after_seconds) from exc
        raise AppError(401, "AUTH_INVALID_CREDENTIALS", "账号或密码错误") from exc
    await limiter.reset(subject)
    return success_response(request, _token_response(pair).model_dump())


@router.post("/refresh")
async def refresh(
    payload: RefreshRequest, request: Request, service: AuthServiceDependency
) -> dict[str, Any]:
    try:
        pair = await service.refresh(payload.refresh_token)
    except AuthenticationError as exc:
        raise AppError(401, "AUTH_INVALID_REFRESH_TOKEN", "刷新令牌无效或已过期") from exc
    return success_response(request, _token_response(pair).model_dump())


@router.post("/logout")
async def logout(
    payload: RefreshRequest, request: Request, service: AuthServiceDependency
) -> dict[str, Any]:
    try:
        await service.logout(payload.refresh_token)
    except AuthenticationError as exc:
        raise AppError(401, "AUTH_INVALID_REFRESH_TOKEN", "刷新令牌无效或已过期") from exc
    return success_response(request)


@router.post("/ws-token")
async def issue_websocket_token(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    service = getattr(request.app.state, "websocket_token_service", None)
    if service is None:
        raise AppError(503, "CHAT_RUNTIME_UNAVAILABLE", "WebSocket chat is unavailable")
    token = await service.issue(principal.user_id)
    return success_response(
        request,
        WebSocketTokenResponse(ws_token=token, expires_in=service.ttl_seconds).model_dump(),
    )


def _token_response(pair: TokenPair) -> TokenResponse:
    now = datetime.now(UTC)
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=max(0, ceil((pair.access_expires_at - now).total_seconds())),
        refresh_expires_in=max(0, ceil((pair.refresh_expires_at - now).total_seconds())),
    )


def _rate_limit_error(retry_after_seconds: int) -> AppError:
    return AppError(
        429,
        "AUTH_RATE_LIMITED",
        "登录失败次数过多，请稍后重试",
        headers={"Retry-After": str(max(1, retry_after_seconds))},
    )
