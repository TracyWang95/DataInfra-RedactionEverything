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
from starlette.responses import Response, JSONResponse

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
        if request.method not in _SAFE_METHODS and not exempt:
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

        # --- Ensure cookie is set on every response ----------------------
        if _COOKIE_NAME not in request.cookies:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                key=_COOKIE_NAME,
                value=token,
                httponly=False,  # JS must read this cookie
                samesite="strict",
                secure=False,  # DEV ONLY: local tool runs on HTTP; MUST set True in production behind HTTPS
                path="/",
            )

        return response
