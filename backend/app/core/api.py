import logging
import time
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
from app.core.observability import bind_log_context, reset_log_context

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
    if request.url.path == "/v1/chat/completions":
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "message": message,
                    "type": _openai_error_type(status_code),
                    "param": _openai_error_param(details),
                    "code": code.lower(),
                }
            },
        )
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": get_request_id(request),
        },
    )


def _openai_error_type(status_code: int) -> str:
    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        return "permission_error"
    if status_code == 429:
        return "rate_limit_error"
    if status_code >= 500:
        return "server_error"
    return "invalid_request_error"


def _openai_error_param(details: list[dict[str, Any]] | None) -> str | None:
    if not details:
        return None
    field = details[0].get("field")
    if not isinstance(field, str):
        return None
    for prefix in ("body.", "query.", "path."):
        if field.startswith(prefix):
            return field.removeprefix(prefix)
    return field


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
        started_at = time.perf_counter()
        supplied = request.headers.get(settings.request_id_header)
        request.state.request_id = _accepted_request_id(
            supplied, settings.request_id_max_length
        ) or str(uuid7())
        context_tokens = bind_log_context(request_id=request.state.request_id)
        try:
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
            latency_ms = round((time.perf_counter() - started_at) * 1000, 3)
            route = request.scope.get("route")
            route_path = getattr(route, "path", "__unmatched__")
            registry = getattr(request.app.state, "metrics_registry", None)
            if registry is not None:
                registry.observe_request(
                    request.method, route_path, response.status_code, latency_ms
                )
            user_id = getattr(request.state, "user_id", None)
            conversation_id = getattr(request.state, "conversation_id", None)
            if conversation_id is None:
                conversation_id = request.path_params.get("conversation_id")
            if response.status_code >= 500:
                log_method = logger.error
            elif response.status_code >= 400:
                log_method = logger.warning
            else:
                log_method = logger.info
            log_method(
                "HTTP request completed",
                extra={
                    "request_id": request.state.request_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "latency_ms": latency_ms,
                    "details": {
                        "method": request.method,
                        "route": route_path,
                        "status_code": response.status_code,
                    },
                },
            )
            response.headers[settings.request_id_header] = request.state.request_id
            return response
        finally:
            reset_log_context(context_tokens)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        response = error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
        response.headers.update(exc.headers)
        return response

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
