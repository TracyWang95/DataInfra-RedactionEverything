"""R1-3：按用户限流依赖 + audit 轮转配置。"""
from __future__ import annotations

import asyncio
import logging.handlers

import pytest
from fastapi import HTTPException

from app.core.rate_limit import RateLimiter, make_user_throttle


def test_user_throttle_blocks_after_limit(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", False)  # require_auth → anonymous
    dep = make_user_throttle(RateLimiter(max_requests=3, window_seconds=60), "upload")

    async def run():
        for _ in range(3):
            await dep(subject="alice")
        with pytest.raises(HTTPException) as exc:
            await dep(subject="alice")
        assert exc.value.status_code == 429
        # 其他用户不受影响（按 subject 计数）
        await dep(subject="bob")

    asyncio.run(run())


def test_audit_logger_uses_rotation():
    from app.core import audit

    handlers = audit._audit_logger.handlers
    assert any(
        isinstance(h, logging.handlers.RotatingFileHandler) and h.maxBytes > 0
        for h in handlers
    ), "audit log must rotate (compliance log grew unbounded before)"
