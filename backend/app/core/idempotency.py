# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Simple in-memory idempotency key store for POST endpoints."""
import time
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

# key -> (timestamp, response_data)
_store: dict[str, tuple[float, Any]] = {}
_TTL = 3600  # 1 hour


def _cleanup():
    """Remove expired entries."""
    now = time.monotonic()
    expired = [k for k, (ts, _) in _store.items() if now - ts > _TTL]
    for k in expired:
        del _store[k]


def check_idempotency(key: Optional[str]) -> Optional[Any]:
    """Check if an idempotency key has been used. Returns cached response or None."""
    if not key:
        return None
    _cleanup()
    entry = _store.get(key)
    if entry:
        logger.debug("Idempotency key hit: %s", key)
        return entry[1]
    return None


def save_idempotency(key: Optional[str], response_data: Any) -> None:
    """Save response for an idempotency key."""
    if not key:
        return
    _store[key] = (time.monotonic(), response_data)
