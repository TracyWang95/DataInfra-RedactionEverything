#!/usr/bin/env python3
"""Run value-blind DIMSE C-ECHO and optional C-STORE through DCMTK."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _binary(name: str, environment: str) -> str | None:
    configured = os.environ.get(environment)
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which(name)
    if found:
        return found
    for pattern in (f"tmp/dicom-tools/**/{name}.exe", f"tmp/dcmtk-portable/**/{name}.exe"):
        candidate = next(REPO_ROOT.glob(pattern), None)
        if candidate:
            return str(candidate)
    return None


def _run(command: list[str], timeout: float) -> dict[str, object]:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
    diagnostic = completed.stdout + b"\0" + completed.stderr
    return {
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout_bytes": len(completed.stdout),
        "stderr_bytes": len(completed.stderr),
        "diagnostic_sha256": hashlib.sha256(diagnostic).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--called-aet", default="ANY-SCP")
    parser.add_argument("--calling-aet", default="DICOM-VALIDATOR")
    parser.add_argument("--store-file", type=Path)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.store_file and not args.allow_write:
        parser.error("--store-file requires --allow-write")
    echoscu = _binary("echoscu", "ECHOSCU_PATH")
    if not echoscu:
        print("ERROR: echoscu not found; run tools/dicom_compat/fetch_dcmtk.py", file=sys.stderr)
        return 2
    report: dict[str, object] = {"schema_version": 1, "value_blind": True, "operations": {}}
    try:
        echo = _run(
            [echoscu, "-aec", args.called_aet, "-aet", args.calling_aet, args.host, str(args.port)],
            args.timeout,
        )
        report["operations"]["c_echo"] = echo  # type: ignore[index]
        if args.store_file:
            storescu = _binary("storescu", "STORESCU_PATH")
            if not storescu:
                raise ValueError("storescu not found")
            store = _run(
                [
                    storescu,
                    "-aec",
                    args.called_aet,
                    "-aet",
                    args.calling_aet,
                    args.host,
                    str(args.port),
                    str(args.store_file),
                ],
                args.timeout,
            )
            report["operations"]["c_store"] = store  # type: ignore[index]
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    operations = report["operations"]
    report["passed"] = bool(operations) and all(item["success"] for item in operations.values())  # type: ignore[union-attr]
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

