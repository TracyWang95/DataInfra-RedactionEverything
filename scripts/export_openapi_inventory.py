#!/usr/bin/env python3
"""Export OpenAPI spec (openapi.json) for RedactionEverything.

Scenario-flow API docs are maintained in docs/api-inventory.md (not auto-generated).
"""
from __future__ import annotations

import json
import os
import sys

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from app.main import app  # noqa: E402


def main() -> None:
    spec = app.openapi()
    repo_root = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
    docs_dir = os.path.join(repo_root, "docs")
    os.makedirs(docs_dir, exist_ok=True)

    json_path = os.path.join(docs_dir, "openapi.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, ensure_ascii=False, indent=2)

    path_count = len(spec.get("paths", {}))
    print(f"Exported OpenAPI {spec.get('openapi')} — {path_count} paths")
    print(f"  {json_path}")
    print("  Scenario docs: docs/api-inventory.md (manual, flow-based)")


if __name__ == "__main__":
    main()
