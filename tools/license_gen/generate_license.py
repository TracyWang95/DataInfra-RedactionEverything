#!/usr/bin/env python3
"""Offline Ed25519 license generator (vendor side only).

Usage:
    python generate_license.py keygen --out priv.pem
    python generate_license.py issue --customer "客户名" --expires 2027-06-30 \
        --max-users 50 --edition enterprise --industries legal,medical \
        --key priv.pem --out license.json

Signing uses the SAME canonical-bytes helper as the backend verifier
(app.core.license.canonical_payload_bytes), so signer and verifier can never
drift. Run inside the backend virtualenv.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.license import canonical_payload_bytes  # noqa: E402


def _pubkey_hex(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return raw.hex()


def cmd_keygen(args: argparse.Namespace) -> int:
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    out = Path(args.out)
    out.write_bytes(pem)
    print(f"Private key written to {out}")
    print(f"PUBLIC_KEY_HEX = {_pubkey_hex(private_key)}")
    print("Bake this hex into backend/app/core/license_pubkey.py for the matching build.")
    return 0


def cmd_issue(args: argparse.Namespace) -> int:
    expires = date.fromisoformat(args.expires)  # validates YYYY-MM-DD
    private_key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SystemExit("--key must be an Ed25519 private key PEM (from `keygen`)")

    industries = [item.strip() for item in args.industries.split(",") if item.strip()]
    payload = {
        "schema": 1,
        "license_id": uuid.uuid4().hex,
        "customer": args.customer,
        "issued_at": datetime.now(UTC).strftime("%Y-%m-%d"),
        "expires_at": expires.isoformat(),
        "max_users": args.max_users,
        "edition": args.edition,
        "features": {"industries": industries},
    }
    signature = private_key.sign(canonical_payload_bytes(payload))
    document = {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}

    # Self-verify before writing anything (raises InvalidSignature on failure).
    private_key.public_key().verify(signature, canonical_payload_bytes(payload))

    out = Path(args.out)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"License written to {out} (self-verify OK)")
    print(f"  license_id : {payload['license_id']}")
    print(f"  customer   : {payload['customer']}")
    print(f"  edition    : {payload['edition']}")
    print(f"  expires_at : {payload['expires_at']}  max_users: {payload['max_users']}")
    print(f"  industries : {', '.join(industries) or '-'}")
    print(f"  pubkey_hex : {_pubkey_hex(private_key)} (must match license_pubkey.PUBLIC_KEY_HEX)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Ed25519 license generator (vendor side)")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="generate a new Ed25519 keypair")
    keygen.add_argument("--out", required=True, help="private key PEM output path")
    keygen.set_defaults(func=cmd_keygen)

    issue = sub.add_parser("issue", help="sign and write a license.json")
    issue.add_argument("--customer", required=True)
    issue.add_argument("--expires", required=True, help="YYYY-MM-DD")
    issue.add_argument("--max-users", type=int, required=True)
    issue.add_argument("--edition", default="enterprise")
    issue.add_argument("--industries", default="", help="comma separated, e.g. legal,medical")
    issue.add_argument("--key", required=True, help="private key PEM from `keygen`")
    issue.add_argument("--out", required=True, help="license.json output path")
    issue.set_defaults(func=cmd_issue)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
