"""Simple in-memory rate limiter (no external dependencies)."""
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiter:
    """Token-bucket-style per-IP rate limiter."""

    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        # Remove expired entries
        self._hits[key] = [t for t in hits if now - t < self.window]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
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
