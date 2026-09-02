"""Shared helpers for DICOM tests; no network access occurs during pytest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
ASSET_ROOT = Path(__file__).resolve().parent / "assets" / "dicom"
MANIFEST_PATH = ASSET_ROOT / "manifest.json"
CACHE_ROOT = ASSET_ROOT / "cache"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def samples_by_id() -> dict[str, dict[str, Any]]:
    return {sample["id"]: sample for sample in manifest()["samples"]}


def sample_path(sample: dict[str, Any]) -> Path:
    return CACHE_ROOT / sample["path"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

