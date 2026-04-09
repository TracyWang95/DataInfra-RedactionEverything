# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Verify requirements.lock is consistent with requirements.txt."""
from __future__ import annotations

import os
import re

import pytest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _parse_pinned_packages(path: str) -> dict[str, str]:
    """Parse a requirements file and return {lowercase_name: version_spec} for pinned (==) packages."""
    result = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Match package==version (possibly with extras and markers)
            m = re.match(r"([A-Za-z0-9_.-]+)(?:\[.*?\])?\s*==\s*([^\s;]+)", line)
            if m:
                result[m.group(1).lower()] = m.group(2)
    return result


def _parse_all_packages(path: str) -> set[str]:
    """Parse a requirements file and return the set of lowercase package names."""
    result: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"([A-Za-z0-9_.-]+)", line)
            if m:
                result.add(m.group(1).lower())
    return result


def test_lock_file_has_no_todo_comment():
    """The lock file should not contain a TODO placeholder comment."""
    lock_path = os.path.join(BACKEND_DIR, "requirements.lock")
    with open(lock_path, encoding="utf-8") as f:
        content = f.read()
    assert "TODO" not in content, "requirements.lock should not contain TODO comments"


def test_lock_file_uses_pinned_versions():
    """Every non-comment, non-empty line in the lock file should use == pinning."""
    lock_path = os.path.join(BACKEND_DIR, "requirements.lock")
    with open(lock_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert "==" in line, (
                f"requirements.lock line {lineno}: '{line}' is not pinned with =="
            )


def test_lock_matches_requirements_txt_pinned_versions():
    """Packages pinned with == in requirements.txt must have matching versions in the lock file."""
    req_path = os.path.join(BACKEND_DIR, "requirements.txt")
    lock_path = os.path.join(BACKEND_DIR, "requirements.lock")

    req_pinned = _parse_pinned_packages(req_path)
    lock_pinned = _parse_pinned_packages(lock_path)

    for pkg, version in req_pinned.items():
        assert pkg in lock_pinned, f"Package '{pkg}' pinned in requirements.txt but missing from lock"
        assert lock_pinned[pkg] == version, (
            f"Package '{pkg}': requirements.txt pins {version} but lock has {lock_pinned[pkg]}"
        )


def test_lock_covers_all_requirements_txt_packages():
    """Every package listed in requirements.txt must have a pinned entry in the lock file."""
    req_path = os.path.join(BACKEND_DIR, "requirements.txt")
    lock_path = os.path.join(BACKEND_DIR, "requirements.lock")

    req_packages = _parse_all_packages(req_path)
    lock_packages = _parse_all_packages(lock_path)

    missing = sorted(req_packages - lock_packages)
    assert not missing, (
        f"Packages in requirements.txt but missing from requirements.lock: {missing}"
    )
