"""CSRF protection via the double-submit cookie pattern."""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Login/setup must work before a CSRF cookie exists. Everything else that
# changes auth state should still require the double-submit check.
_EXEMPT_MUTATING_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/setup",
    "/api/v1/auth/register",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/metrics",
    "/",
)

_AUTH_ROTATE_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/setup",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
)

_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "x-csrf-token"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path

        exempt = path == "/" or any(
            path.startswith(prefix) for prefix in _EXEMPT_MUTATING_PREFIXES if prefix != "/"
        )

        # Non-browser Bearer-token clients are not vulnerable to CSRF because
        # the attacker cannot cause the browser to attach that header.
        has_bearer = (request.headers.get("authorization") or "").startswith("Bearer ")

        if request.method not in _SAFE_METHODS and not exempt and not has_bearer and settings.AUTH_ENABLED:
            cookie_token = request.cookies.get(_COOKIE_NAME)
            header_token = request.headers.get(_HEADER_NAME)

            if not cookie_token or not header_token:
                return JSONResponse(status_code=403, content={"detail": "Missing CSRF token."})
            if not secrets.compare_digest(cookie_token, header_token):
                return JSONResponse(status_code=403, content={"detail": "CSRF token does not match."})

        response: Response = await call_next(request)

        is_auth_change = request.method == "POST" and any(
            path.startswith(prefix) for prefix in _AUTH_ROTATE_PREFIXES
        )

        if _COOKIE_NAME not in request.cookies or is_auth_change:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                key=_COOKIE_NAME,
                value=token,
                httponly=False,
                samesite="strict",
                secure=not settings.DEBUG,
                path="/",
            )

        return response
