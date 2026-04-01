"""Tests for app.core.circuit_breaker -- simple circuit breaker."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.core.circuit_breaker import CircuitBreaker


@pytest.fixture
def cb() -> CircuitBreaker:
    return CircuitBreaker("test", threshold=3, reset_timeout=0.2)


def test_normal_operation(cb: CircuitBreaker) -> None:
    result = cb.call_sync(lambda x: x * 2, 5)
    assert result == 10
    assert cb._state == "closed"
    assert cb._failure_count == 0


def test_opens_after_failures(cb: CircuitBreaker) -> None:
    def fail():
        raise ValueError("boom")

    for _ in range(3):
        with pytest.raises(ValueError):
            cb.call_sync(fail)

    assert cb._state == "open"
    # Further calls should raise RuntimeError without calling the function
    with pytest.raises(RuntimeError, match="暂时不可用"):
        cb.call_sync(lambda: "should not run")


def test_half_open_recovery(cb: CircuitBreaker) -> None:
    def fail():
        raise ValueError("boom")

    # Trip the breaker
    for _ in range(3):
        with pytest.raises(ValueError):
            cb.call_sync(fail)
    assert cb._state == "open"

    # Simulate time passing beyond reset_timeout by patching time.monotonic
    original_last_failure = cb._last_failure
    with patch("time.monotonic", return_value=original_last_failure + 0.3):
        # is_open should transition to half-open and allow one call
        assert cb.is_open is False
        assert cb._state == "half-open"

        # A successful call should close the circuit
    # Actually call outside the patch so monotonic works normally
    cb._state = "half-open"
    result = cb.call_sync(lambda: "recovered")
    assert result == "recovered"
    assert cb._state == "closed"
    assert cb._failure_count == 0
