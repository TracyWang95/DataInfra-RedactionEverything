#!/usr/bin/env python3
"""Value-blind QIDO-RS/WADO-RS/STOW-RS interoperability probe.

Search and retrieve are read-only.  STOW-RS is disabled unless both a file and
``--allow-write`` are supplied.  Reports contain status, media type, byte
counts and payload hashes, never DICOM metadata or response bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx


def _summary(response: httpx.Response) -> dict[str, object]:
    return {
        "status": response.status_code,
        "success": response.is_success,
        "content_type": response.headers.get("content-type", "").split(";", 1)[0].lower(),
        "bytes": len(response.content),
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
    }


def _multipart_dicom(path: Path) -> tuple[bytes, str]:
    boundary = f"dicom-{uuid.uuid4().hex}"
    payload = path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/dicom\r\n\r\n"
    ).encode("ascii") + payload + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f'multipart/related; type="application/dicom"; boundary={boundary}'


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    base = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    results: dict[str, object] = {"schema_version": 1, "value_blind": True, "operations": {}}
    with httpx.Client(headers=headers, timeout=args.timeout, verify=not args.insecure) as client:
        qido = client.get(
            f"{base}/studies",
            params={"limit": args.limit},
            headers={"Accept": "application/dicom+json"},
        )
        results["operations"]["qido_studies"] = _summary(qido)  # type: ignore[index]

        if args.study_uid and args.series_uid and args.instance_uid:
            resource = (
                f"{base}/studies/{quote(args.study_uid, safe='')}"
                f"/series/{quote(args.series_uid, safe='')}"
                f"/instances/{quote(args.instance_uid, safe='')}"
            )
            wado = client.get(resource, headers={"Accept": 'multipart/related; type="application/dicom"'})
            results["operations"]["wado_instance"] = _summary(wado)  # type: ignore[index]

        if args.stow_file:
            if not args.allow_write:
                raise ValueError("--stow-file requires --allow-write")
            body, content_type = _multipart_dicom(args.stow_file)
            stow = client.post(f"{base}/studies", content=body, headers={"Content-Type": content_type})
            results["operations"]["stow_instance"] = _summary(stow)  # type: ignore[index]
    operations = results["operations"]
    results["passed"] = bool(operations) and all(item["success"] for item in operations.values())  # type: ignore[union-attr]
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="DICOMweb service root, e.g. http://host/dicom-web")
    parser.add_argument("--token")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--study-uid")
    parser.add_argument("--series-uid")
    parser.add_argument("--instance-uid")
    parser.add_argument("--stow-file", type=Path)
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="disable TLS verification for a controlled test endpoint")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    uid_args = (args.study_uid, args.series_uid, args.instance_uid)
    if any(uid_args) and not all(uid_args):
        parser.error("WADO requires --study-uid, --series-uid, and --instance-uid together")
    try:
        report = run_probe(args)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

