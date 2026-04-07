# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Unified error response handling."""
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_id import request_id_var


class AppError(Exception):
    """Application error with error code."""
    def __init__(self, status_code: int, error_code: str, message: str, detail: dict = None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail or {}


def _error_response(status_code: int, error_code: str, message: str, detail: dict = None) -> JSONResponse:
    # 使用 request_id middleware 中已设置的请求 ID，而非每次生成新 uuid
    rid = request_id_var.get("")
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "detail": detail or {},
            "request_id": rid,
        },
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(exc.status_code, exc.error_code, exc.message, exc.detail)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # 避免将内部异常细节泄露给客户端
    if isinstance(exc.detail, str):
        # 仅对 4xx 暴露原始消息，5xx 使用通用消息
        message = exc.detail if exc.status_code < 500 else "服务器内部错误"
    else:
        message = "请求错误"
    return _error_response(
        exc.status_code,
        f"HTTP_{exc.status_code}",
        message,
        exc.detail if isinstance(exc.detail, dict) else {},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Sanitize Pydantic errors: expose field location + user-friendly message only
    safe_errors = []
    for err in exc.errors():
        loc = " → ".join(str(l) for l in err.get("loc", []) if l != "body")
        safe_errors.append({
            "field": loc or "(root)",
            "message": err.get("msg", "校验失败"),
        })
    return _error_response(
        422,
        "VALIDATION_ERROR",
        "请求参数校验失败",
        {"errors": safe_errors},
    )
