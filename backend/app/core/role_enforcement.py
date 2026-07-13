"""Centralised role enforcement middleware (Phase 1a role matrix).

One chokepoint instead of per-endpoint dependencies:
  viewer    -> only safe methods on /api/*; own auth endpoints stay allowed
  operator  -> everything except review decisions (approve/reject/commit/
               commit-all) and redaction execution via review
  reviewer / user / super_admin -> untouched here (fine-grained gates such as
               require_super_admin / require_bulk_confirm still apply)

The role comes from the JWT's `role` claim (create_token embeds it); tokens
minted before the claim existed fall back to the user store. Unauthenticated
or malformed tokens pass through — the endpoint's own auth dependency returns
its usual 401 so error semantics stay unchanged.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Auth self-service must keep working for every role.
_ALWAYS_ALLOWED_PREFIXES = ("/api/v1/auth/",)
_REVIEW_DECISION_MARKERS = (
    "/review/approve",
    "/review/reject",
    "/review/commit",  # also matches /review/commit-all
)


def _role_from_request(request: Request) -> str | None:
    token: str | None = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if token is None:
        token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from app.core.auth import decode_token, get_user

        payload = decode_token(token)
        role = payload.get("role")
        if not role:
            user = get_user(payload.get("sub"))
            role = (user or {}).get("role")
        return str(role) if role else None
    except Exception:
        # Invalid/expired token: let the endpoint's auth dependency produce
        # its normal 401 instead of masking it with a 403 here.
        return None


def _denied(detail: str) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": detail})


class RoleEnforcementMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.AUTH_ENABLED:
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if path.startswith(_ALWAYS_ALLOWED_PREFIXES):
            return await call_next(request)

        role = _role_from_request(request)
        if role == "viewer":
            return _denied("只读账号无权执行此操作。请联系管理员调整角色。")
        if role == "operator" and any(marker in path for marker in _REVIEW_DECISION_MARKERS):
            return _denied("操作员账号无权确认审核。请交由审核员处理。")
        return await call_next(request)
