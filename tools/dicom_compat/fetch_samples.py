#!/usr/bin/env python3
"""Fetch the audited DICOM fixture corpus without committing clinical binaries.

Downloads are pinned to immutable upstream commits and accepted only after
their byte length and SHA-256 digest match ``manifest.json``.  Existing files
are never trusted solely by name: they are verified on every invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "backend" / "tests" / "assets" / "dicom"
DEFAULT_MANIFEST = ASSET_ROOT / "manifest.json"
DEFAULT_DESTINATION = ASSET_ROOT / "cache"
CHUNK_BYTES = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema_version") != 1:
        raise ValueError(f"Unsupported manifest schema: {manifest.get('schema_version')!r}")
    return manifest


def verify_file(path: Path, sample: dict[str, Any]) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    expected_size = int(sample["bytes"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        return False, f"size {actual_size} != {expected_size}"
    actual_hash = _sha256(path)
    if actual_hash.lower() != str(sample["sha256"]).lower():
        return False, f"sha256 {actual_hash} != {sample['sha256']}"
    return True, "verified"


def _safe_destination(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / Path(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Fixture path escapes destination: {relative_path!r}") from exc
    return candidate


def _download(sample: dict[str, Any], destination: Path, *, timeout: float) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(
        sample["url"],
        headers={"User-Agent": "DataInfra-DICOM-fixture-fetcher/1.0"},
    )
    digest = hashlib.sha256()
    total = 0
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response, partial.open("wb") as out:
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        if total != int(sample["bytes"]):
            raise ValueError(f"downloaded {total} bytes, expected {sample['bytes']}")
        actual = digest.hexdigest()
        if actual.lower() != str(sample["sha256"]).lower():
            raise ValueError(f"downloaded SHA-256 {actual}, expected {sample['sha256']}")
        os.replace(partial, destination)
    finally:
        if partial.exists():
            partial.unlink()


def select_samples(
    manifest: dict[str, Any],
    *,
    ids: set[str] | None = None,
    features: set[str] | None = None,
) -> list[dict[str, Any]]:
    samples = list(manifest["samples"])
    if ids:
        known = {sample["id"] for sample in samples}
        missing = ids - known
        if missing:
            raise ValueError(f"Unknown sample id(s): {', '.join(sorted(missing))}")
        samples = [sample for sample in samples if sample["id"] in ids]
    if features:
        samples = [sample for sample in samples if features.issubset(set(sample.get("features", [])))]
    return samples


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--id", action="append", dest="ids", help="fetch one sample id; repeatable")
    parser.add_argument("--feature", action="append", dest="features", help="require feature; repeatable")
    parser.add_argument("--verify-only", action="store_true", help="do not access the network")
    parser.add_argument("--list", action="store_true", help="list matching samples and exit")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(args.manifest)
    try:
        samples = select_samples(
            manifest,
            ids=set(args.ids or []),
            features=set(args.features or []),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for sample in samples:
            print(
                f"{sample['id']:<30} {sample['category']:<16} "
                f"{sample.get('modality') or '-':<3} {sample['bytes']:>8}  {sample['path']}"
            )
        return 0

    failures = 0
    for sample in samples:
        path = _safe_destination(args.destination, sample["path"])
        ok, detail = verify_file(path, sample)
        if ok:
            print(f"OK       {sample['id']}: {detail}")
            continue
        if args.verify_only:
            print(f"MISSING  {sample['id']}: {detail}")
            failures += 1
            continue
        print(f"FETCH    {sample['id']}: {sample['url']}")
        try:
            _download(sample, path, timeout=args.timeout)
            ok, detail = verify_file(path, sample)
            if not ok:
                raise ValueError(detail)
            print(f"OK       {sample['id']}: verified")
        except Exception as exc:  # command-line boundary: report and continue corpus fetch
            print(f"FAILED   {sample['id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
    print(f"Selected {len(samples)} fixture(s); failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

