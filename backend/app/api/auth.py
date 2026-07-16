from datetime import UTC, datetime
from math import ceil
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.application.auth import AuthenticationError, AuthService, TokenPair
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


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/login")
async def login(
    payload: LoginRequest, request: Request, service: AuthServiceDependency
) -> dict[str, Any]:
    try:
        pair = await service.login(payload.username, payload.password)
    except AuthenticationError as exc:
        raise AppError(401, "AUTH_INVALID_CREDENTIALS", "账号或密码错误") from exc
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


def _token_response(pair: TokenPair) -> TokenResponse:
    now = datetime.now(UTC)
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=max(0, ceil((pair.access_expires_at - now).total_seconds())),
        refresh_expires_in=max(0, ceil((pair.refresh_expires_at - now).total_seconds())),
    )
