# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Simple circuit breaker for external service calls."""
import time
import logging

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self, name: str, threshold: int = 5, reset_timeout: float = 30.0):
        self.name = name
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self._failure_count = 0
        self._last_failure: float = 0.0
        self._state = "closed"

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            if time.monotonic() - self._last_failure > self.reset_timeout:
                self._state = "half-open"
                return False
            return True
        return False

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure = time.monotonic()
        if self._failure_count >= self.threshold:
            self._state = "open"
            logger.warning("Circuit breaker [%s] OPEN after %d failures", self.name, self._failure_count)

    def call_sync(self, func, *args, **kwargs):
        if self.is_open:
            raise RuntimeError(f"服务 [{self.name}] 暂时不可用，请稍后重试")
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

ocr_breaker = CircuitBreaker("OCR", threshold=5, reset_timeout=30.0)
ner_breaker = CircuitBreaker("NER/HaS", threshold=3, reset_timeout=30.0)
vision_breaker = CircuitBreaker("Vision", threshold=5, reset_timeout=30.0)
