#!/usr/bin/env python3
"""Install a pinned portable OFFIS DCMTK build under ignored local tooling.

This avoids administrator privileges and does not change PATH.  The URL and
SHA-256 below identify the OFFIS Windows 64-bit DCMTK 3.7.0 package used by
the Chocolatey recipe maintained for DCMTK.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION = REPO_ROOT / "tmp" / "dicom-tools" / "dcmtk-3.7.0"
URL = "https://dcmtk.org/chocolatey/dcmtk-3.7.0-win64-chocolatey.zip"
SHA256 = "a99e38e77241d6ef592bb4b1f0b3e975bd995c13c2e22ec82f1db8e0c6277acd"


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (root / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"unsafe ZIP member: {member.filename!r}") from exc
        package.extractall(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    destination = args.destination.resolve()
    binary = next(destination.rglob("dcmdump.exe"), None) if destination.exists() else None
    if binary:
        print(binary)
        return 0
    if args.verify_only:
        print("DCMTK portable binary is not installed", file=sys.stderr)
        return 1
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "dcmtk-3.7.0-win64-chocolatey.zip"
    partial = archive.with_suffix(".zip.part")
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "DataInfra-DICOM-validator/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        os.replace(partial, archive)
        actual = _digest(archive)
        if actual != SHA256:
            raise ValueError(f"DCMTK SHA-256 mismatch: {actual} != {SHA256}")
        _safe_extract(archive, destination)
    finally:
        if partial.exists():
            partial.unlink()
    binary = next(destination.rglob("dcmdump.exe"), None)
    if not binary:
        print("dcmdump.exe missing after extraction", file=sys.stderr)
        return 1
    print(binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

