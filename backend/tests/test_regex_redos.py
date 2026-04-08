# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for ReDoS protection in safe_regex and regex_service."""

import re
import pytest

from app.core.safe_regex import RegexTimeoutError, safe_compile, safe_finditer


class TestSafeCompile:
    """safe_compile should reject patterns that cause catastrophic backtracking."""

    def test_known_redos_pattern_times_out(self):
        """(a+)+$ is a classic ReDoS pattern — should raise RegexTimeoutError."""
        with pytest.raises(RegexTimeoutError):
            safe_compile(r"(a+)+$", timeout=1.0)

    def test_normal_pattern_compiles(self):
        """A simple pattern should compile without issues."""
        compiled = safe_compile(r"\d{3}-\d{4}")
        assert isinstance(compiled, re.Pattern)

    def test_invalid_syntax_raises_re_error(self):
        """A syntactically invalid pattern should raise re.error, not timeout."""
        with pytest.raises(re.error):
            safe_compile(r"[unclosed")


class TestSafeFinditer:
    """safe_finditer should enforce a wall-clock timeout on matching."""

    def test_normal_match(self):
        """Normal finditer should return matches."""
        compiled = safe_compile(r"\d+")
        matches = safe_finditer(compiled, "abc 123 def 456")
        texts = [m.group() for m in matches]
        assert texts == ["123", "456"]

    def test_empty_match(self):
        """No matches should return an empty list."""
        compiled = safe_compile(r"zzz")
        matches = safe_finditer(compiled, "abc 123")
        assert matches == []
