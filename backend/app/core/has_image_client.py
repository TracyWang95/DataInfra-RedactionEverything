"""主后端调用 HaS Image 微服务 (8081)。"""
from __future__ import annotations

import base64
from typing import Any, List, Optional

import httpx

from app.core.config import settings
from app.core.retry import retry_async, RETRYABLE_HTTPX


async def _do_detect_request(url: str, body: dict) -> httpx.Response:
    """Execute a single detect HTTP request (retryable)."""
    async with httpx.AsyncClient(timeout=settings.HAS_IMAGE_TIMEOUT, trust_env=False) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        return resp


async def detect_privacy_regions(
    image_data: bytes,
    conf: Optional[float] = None,
    category_slugs: Optional[List[str]] = None,
) -> List[dict[str, Any]]:
    """
    返回服务端 boxes 列表 dict:
    x, y, width, height (0-1), category (slug), confidence
    """
    url = f"{settings.HAS_IMAGE_BASE_URL.rstrip('/')}/detect"
    b64 = base64.b64encode(image_data).decode("utf-8")
    c = settings.HAS_IMAGE_CONF if conf is None else conf
    body: dict = {"image_base64": b64, "conf": c}
    if category_slugs is not None:
        body["categories"] = category_slugs
    resp = await retry_async(
        _do_detect_request, url, body,
        max_retries=2, base_delay=1.0,
        retryable_exceptions=RETRYABLE_HTTPX,
    )
    data = resp.json()
    return list(data.get("boxes") or [])
