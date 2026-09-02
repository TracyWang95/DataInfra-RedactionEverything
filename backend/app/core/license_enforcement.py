"""Centralised offline-license enforcement middleware (W2).

One chokepoint modeled on app.core.role_enforcement: when license enforcement
is enabled and the license is in a non-usable state (grace_readonly, blocked,
invalid), every mutating /api/ request is rejected with 403 + the license
state. Reads stay available so operators can inspect the system, and the auth
and license endpoints stay open so a super admin can log in and upload a
renewal license.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.core.config import settings
from app.core.errors import error_response
from app.core.license import STATE_BLOCKED, STATE_GRACE_READONLY, STATE_INVALID, get_license_state

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Login and license renewal must keep working in every license state.
_ALWAYS_ALLOWED_PREFIXES = ("/api/v1/auth/", "/api/v1/license/")

_STATE_MESSAGES = {
    STATE_GRACE_READONLY: "License 已过期，系统处于只读宽限期。请上传新的 License 以恢复写入操作。",
    STATE_BLOCKED: "License 已过期且超出宽限期，写入操作已锁定。请联系供应商续期。",
    STATE_INVALID: "License 缺失或无效，写入操作已禁用。请由超级管理员上传有效 License。",
}


class LicenseEnforcementMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.LICENSE_ENFORCEMENT_ENABLED:
            return await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if path.startswith(_ALWAYS_ALLOWED_PREFIXES):
            return await call_next(request)

        state = get_license_state()
        message = _STATE_MESSAGES.get(state.state)
        if message is not None:
            license_detail = {
                "state": state.state,
                "reason": state.reason,
                "expires_at": state.expires_at or None,
                "days_left": state.days_left,
            }
            return error_response(
                403,
                "LICENSE_WRITE_FORBIDDEN",
                message,
                {"license": license_detail},
                extra={"license": license_detail},
            )
        return await call_next(request)
