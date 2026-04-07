# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Simple in-memory rate limiter with bounded memory (no external dependencies)."""
import threading
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 最大跟踪的不同 IP 数，超过后淘汰最旧条目，防止内存无限增长
_MAX_TRACKED_IPS = 10_000


class RateLimiter:
    """Token-bucket-style per-IP rate limiter with LRU eviction."""

    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._lock = threading.Lock()
        # OrderedDict 用作 LRU：最近访问的 key move_to_end
        self._hits: OrderedDict[str, list[float]] = OrderedDict()

    def check(self, key: str) -> bool:
        now = time.monotonic()

        with self._lock:
            # 清理过期条目 + LRU 淘汰
            if len(self._hits) >= _MAX_TRACKED_IPS and key not in self._hits:
                # 淘汰最旧的 IP 条目
                self._hits.popitem(last=False)

            hits = self._hits.get(key, [])
            # Remove expired entries
            hits = [t for t in hits if now - t < self.window]
            if len(hits) >= self.max_requests:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            # 标记为最近使用
            self._hits.move_to_end(key)
            return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """BaseHTTPMiddleware wrapper for RateLimiter (compatible with other BaseHTTPMiddleware)."""

    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self._limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if not self._limiter.check(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后重试",
                    "detail": {},
                },
            )
        return await call_next(request)
