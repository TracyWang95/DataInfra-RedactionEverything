"""CSRF protection via double-submit cookie pattern.

How it works:
- On every response (GET or mutating), set a ``csrf_token`` cookie if absent.
- On state-changing requests (POST / PUT / DELETE / PATCH), require that the
  ``X-CSRF-Token`` header matches the ``csrf_token`` cookie value.
- Auth endpoints (``/api/v1/auth/*``) are exempt so that login works without
  a prior page load.
- Non-browser clients that never receive cookies are unaffected as long as
  they use Bearer JWT auth (CSRF is a browser-only attack vector).
"""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Paths that are exempt from CSRF validation (login / setup must work
# without a prior GET to obtain the cookie).
_EXEMPT_PREFIXES = (
    "/api/v1/auth/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/metrics",
    "/",
)

# Auth state-change paths where CSRF token should be rotated
_AUTH_ROTATE_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/setup",
    "/api/v1/auth/logout",
)

_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "x-csrf-token"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        path = request.url.path

        # --- Exempt paths ------------------------------------------------
        exempt = path == "/" or any(
            path.startswith(p) for p in _EXEMPT_PREFIXES if p != "/"
        )

        # --- Validate on mutating methods --------------------------------
        # Non-browser clients using Bearer JWT auth are not vulnerable to
        # CSRF, so skip validation when an Authorization header is present.
        # Also skip when auth is entirely disabled (no sessions to protect).
        has_bearer = (request.headers.get("authorization") or "").startswith("Bearer ")

        if request.method not in _SAFE_METHODS and not exempt and not has_bearer and settings.AUTH_ENABLED:
            cookie_token = request.cookies.get(_COOKIE_NAME)
            header_token = request.headers.get(_HEADER_NAME)

            if not cookie_token or not header_token:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "缺少 CSRF token"},
                )
            if not secrets.compare_digest(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token 不匹配"},
                )

        # --- Call downstream ---------------------------------------------
        response: Response = await call_next(request)

        # --- Rotate CSRF token on auth state changes ---------------------
        is_auth_change = request.method == "POST" and any(
            path.startswith(p) for p in _AUTH_ROTATE_PREFIXES
        )

        # --- Ensure cookie is set on every response ----------------------
        if _COOKIE_NAME not in request.cookies or is_auth_change:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                key=_COOKIE_NAME,
                value=token,
                httponly=False,  # JS must read this cookie
                samesite="strict",
                secure=not settings.DEBUG,
                path="/",
            )

        return response
