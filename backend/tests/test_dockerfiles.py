# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""Dockerfile sanity checks — verify COPY sources exist and no deprecated packages."""
from __future__ import annotations

import os
import re

import pytest

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _read_dockerfile(name: str) -> str:
    path = os.path.join(BACKEND_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestDockerfileOcr:
    dockerfile = "Dockerfile.ocr"

    def test_no_deprecated_libgl1_mesa_glx(self):
        """libgl1-mesa-glx was removed in Debian Trixie; use libgl1 instead."""
        content = _read_dockerfile(self.dockerfile)
        assert "libgl1-mesa-glx" not in content, (
            f"{self.dockerfile} should use 'libgl1' instead of 'libgl1-mesa-glx'"
        )

    def test_copy_sources_exist(self):
        """All COPY source paths in the Dockerfile should exist relative to backend/."""
        content = _read_dockerfile(self.dockerfile)
        for match in re.finditer(r"^COPY\s+(\S+)", content, re.MULTILINE):
            src = match.group(1)
            if src.startswith("--"):
                continue
            full = os.path.join(BACKEND_DIR, src)
            assert os.path.exists(full), (
                f"{self.dockerfile}: COPY source '{src}' not found at {full}"
            )


class TestDockerfileVision:
    dockerfile = "Dockerfile.vision"

    def test_no_deprecated_libgl1_mesa_glx(self):
        """libgl1-mesa-glx was removed in Debian Trixie; use libgl1 instead."""
        content = _read_dockerfile(self.dockerfile)
        assert "libgl1-mesa-glx" not in content, (
            f"{self.dockerfile} should use 'libgl1' instead of 'libgl1-mesa-glx'"
        )

    def test_copy_sources_exist(self):
        """All COPY source paths in the Dockerfile should exist relative to backend/."""
        content = _read_dockerfile(self.dockerfile)
        for match in re.finditer(r"^COPY\s+(\S+)", content, re.MULTILINE):
            src = match.group(1)
            if src.startswith("--"):
                continue
            full = os.path.join(BACKEND_DIR, src)
            assert os.path.exists(full), (
                f"{self.dockerfile}: COPY source '{src}' not found at {full}"
            )
