import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import uuid7

logger = logging.getLogger(__name__)

RequestHandler = Callable[[Request], Awaitable[Response]]

HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if request_id is not None else str(uuid7())


def success_response(
    request: Request,
    data: Any = None,
    *,
    message: str = "success",
    code: str = "OK",
) -> dict[str, Any]:
    """Build the standard envelope for ordinary REST business endpoints."""
    return {
        "code": code,
        "message": message,
        "data": data,
        "request_id": get_request_id(request),
    }


def error_response(
    request: Request,
    *,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": get_request_id(request),
        },
    )


def _accepted_request_id(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > max_length or "," in candidate:
        return None
    if not all(0x20 <= ord(character) < 0x7F for character in candidate):
        return None
    return candidate


def install_api_contract(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: RequestHandler) -> Response:
        supplied = request.headers.get(settings.request_id_header)
        request.state.request_id = _accepted_request_id(
            supplied, settings.request_id_max_length
        ) or str(uuid7())
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error", extra={"request_id": request.state.request_id}
            )
            response = error_response(
                request,
                status_code=500,
                code="INTERNAL_ERROR",
                message="服务内部错误",
            )
        response.headers[settings.request_id_header] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "reason": error["type"],
            }
            for error in exc.errors()
        ]
        return error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求字段校验失败",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        response = error_response(
            request,
            status_code=exc.status_code,
            code=HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}"),
            message=message,
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response
