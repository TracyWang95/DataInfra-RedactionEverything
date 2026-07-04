# -*- coding: utf-8 -*-
"""Build a versioned release bundle for bare-metal delivery/upgrade.

Usage (repo root):  python deploy/release.py [--skip-build]
Output: dist-release/redaction-release-<version>-<yyyymmddHHMM>.tar.gz
containing backend/app, backend/config, backend/scripts, frontend/dist,
deploy/upgrade.sh and RELEASE.json (version/commit/build time).
The bundle is what deploy/upgrade.sh consumes on the server.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(cmd: list[str], cwd: str | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd or ROOT, text=True, encoding="utf-8").strip()


def main() -> None:
    version = json.load(open(os.path.join(ROOT, "frontend", "package.json"), encoding="utf-8"))[
        "version"
    ]
    commit = sh(["git", "rev-parse", "--short", "HEAD"])
    stamp = time.strftime("%Y%m%d%H%M")

    if "--skip-build" not in sys.argv:
        print("[release] building frontend ...")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.check_call([npm, "run", "build"], cwd=os.path.join(ROOT, "frontend"))

    meta = {
        "version": version,
        "commit": commit,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out_dir = os.path.join(ROOT, "dist-release")
    os.makedirs(out_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, "RELEASE.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    name = f"redaction-release-{version}-{stamp}.tar.gz"
    bundle = os.path.join(out_dir, name)
    include = [
        ("backend/app", "backend/app"),
        ("backend/config", "backend/config"),
        ("backend/scripts", "backend/scripts"),
        ("frontend/dist", "frontend/dist"),
        ("deploy/upgrade.sh", "deploy/upgrade.sh"),
        (meta_path, "RELEASE.json"),
    ]

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        base = os.path.basename(info.name)
        if base == "__pycache__" or base.endswith((".pyc", ".bak")) or ".bak-" in base:
            return None
        return info

    with tarfile.open(bundle, "w:gz") as tar:
        for src, arc in include:
            tar.add(os.path.join(ROOT, src), arcname=arc, filter=_filter)
    size_mb = os.path.getsize(bundle) / 1024 / 1024
    print(f"[release] {name} ({size_mb:.1f} MB)  commit={commit}")


if __name__ == "__main__":
    main()
