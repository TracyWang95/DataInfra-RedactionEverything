"""Simple in-memory rate limiter with bounded memory (no external dependencies)."""
import ipaddress
import threading
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 最大跟踪的不同 IP 数，超过后淘汰最旧条目，防止内存无限增长
_MAX_TRACKED_IPS = 10_000


def _is_trusted_proxy(client_ip: str, trusted_proxies: list[str]) -> bool:
    """Return ``True`` if *client_ip* matches any entry in *trusted_proxies*.

    Each entry can be a single IP (``"127.0.0.1"``), a CIDR block
    (``"172.16.0.0/12"``), or a plain hostname for exact matching.
    Malformed CIDR entries fall back to exact string comparison.
    """
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        # client_ip is not a valid IP (e.g. hostname) — fall back to exact match
        return client_ip in trusted_proxies

    for entry in trusted_proxies:
        try:
            network = ipaddress.ip_network(entry, strict=False)
            if addr in network:
                return True
        except ValueError:
            # Entry is not a valid network — try exact string match
            if client_ip == entry:
                return True
    return False


def get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting ``X-Forwarded-For`` only from trusted proxies.

    The ``X-Forwarded-For`` header is only trusted when the direct peer
    (``request.client.host``) is in the ``TRUSTED_PROXIES`` list.  This
    prevents spoofing when the backend is directly exposed to the internet.
    """
    from app.core.config import get_settings

    direct_ip = request.client.host if request.client else "unknown"

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        trusted = get_settings().TRUSTED_PROXIES
        if _is_trusted_proxy(direct_ip, trusted):
            first_ip = forwarded.split(",")[0].strip()
            if first_ip:
                return first_ip
    return direct_ip


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


# Pre-built limiter instance for upload endpoints (reusable across modules)
upload_limiter = RateLimiter(max_requests=120, window_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """BaseHTTPMiddleware wrapper for RateLimiter (compatible with other BaseHTTPMiddleware)."""

    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self._limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    async def dispatch(self, request: Request, call_next):
        client_ip = get_client_ip(request)
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
