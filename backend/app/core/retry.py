# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Retry utility with exponential backoff for HTTP microservice calls."""
import asyncio
import logging
from typing import TypeVar, Callable, Awaitable

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    fn: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """
    Retry an async function with exponential backoff.

    Args:
        fn: Async function to retry
        max_retries: Maximum number of retry attempts (0 = no retries)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        retryable_exceptions: Tuple of exception types to retry on
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt + 1, max_retries, fn.__name__, delay, e,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("All %d retries exhausted for %s: %s", max_retries, fn.__name__, e)
    raise last_exc  # type: ignore


def retry_sync(
    fn: Callable[..., T],
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple = (Exception,),
    **kwargs,
) -> T:
    """
    Retry a sync function with exponential backoff.

    Args:
        fn: Sync function to retry
        max_retries: Maximum number of retry attempts (0 = no retries)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        retryable_exceptions: Tuple of exception types to retry on
    """
    import time

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_exc = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt + 1, max_retries, fn.__name__, delay, e,
                )
                time.sleep(delay)
            else:
                logger.error("All %d retries exhausted for %s: %s", max_retries, fn.__name__, e)
    raise last_exc  # type: ignore


# Exception types safe to retry (connection / timeout only, NOT 4xx client errors)
RETRYABLE_HTTPX = (
    __import__("httpx").ConnectError,
    __import__("httpx").ReadTimeout,
    __import__("httpx").ConnectTimeout,
    ConnectionError,
    OSError,
)
