"""Unified error response handling."""
import uuid
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Application error with error code."""
    def __init__(self, status_code: int, error_code: str, message: str, detail: dict = None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail or {}


def _error_response(status_code: int, error_code: str, message: str, detail: dict = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "detail": detail or {},
            "request_id": str(uuid.uuid4()),
        },
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(exc.status_code, exc.error_code, exc.message, exc.detail)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error_response(
        exc.status_code,
        f"HTTP_{exc.status_code}",
        str(exc.detail) if isinstance(exc.detail, str) else "请求错误",
        exc.detail if isinstance(exc.detail, dict) else {},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        422,
        "VALIDATION_ERROR",
        "请求参数校验失败",
        {"errors": exc.errors()},
    )
