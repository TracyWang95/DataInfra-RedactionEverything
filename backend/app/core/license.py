"""Offline Ed25519 license verification and cached state (W2).

License file (default ``DATA_DIR/license.json``)::

    {"payload": {...}, "signature": base64(Ed25519 over canonical payload)}

Canonical payload bytes are produced by :func:`canonical_payload_bytes`; the
vendor-side generator in tools/license_gen imports the same helper, so signer
and verifier can never drift.

States:
  unlicensed     enforcement disabled (default) — zero behaviour change
  valid          signature good, outside the expiry warning window
  expiring_soon  valid but <= LICENSE_EXPIRY_WARN_DAYS days to expiry
  grace_readonly expired <= LICENSE_GRACE_DAYS days ago (mutations blocked)
  blocked        expired beyond the grace window
  invalid        missing / tampered / wrong key / bad schema / unreadable

The verified state is cached and re-checked when the license file mtime
changes or LICENSE_RECHECK_INTERVAL_HOURS elapses (same pattern as
``_auth_doc_cache`` in app.core.auth). Expiry comparison is date-only.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core import license_pubkey
from app.core.config import settings

logger = logging.getLogger(__name__)

STATE_UNLICENSED = "unlicensed"
STATE_VALID = "valid"
STATE_EXPIRING_SOON = "expiring_soon"
STATE_GRACE_READONLY = "grace_readonly"
STATE_BLOCKED = "blocked"
STATE_INVALID = "invalid"

# Correctly signed and inside the validity window: only these states grant
# seats; feature flags additionally survive the read-only grace window.
_ACTIVE_STATES = frozenset({STATE_VALID, STATE_EXPIRING_SOON})
_FEATURE_STATES = frozenset({STATE_VALID, STATE_EXPIRING_SOON, STATE_GRACE_READONLY})


def canonical_payload_bytes(payload: dict) -> bytes:
    """Canonical JSON bytes signed by the vendor (shared with tools/license_gen)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class LicenseState:
    state: str
    reason: str = ""
    license_id: str = ""
    customer: str = ""
    edition: str = ""
    expires_at: str = ""
    days_left: int | None = None
    max_users: int | None = None
    features: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def license_file_path() -> str:
    if settings.LICENSE_FILE_PATH:
        return settings.LICENSE_FILE_PATH
    return os.path.join(settings.DATA_DIR, "license.json")


def _invalid(reason: str) -> LicenseState:
    return LicenseState(state=STATE_INVALID, reason=reason)


def verify_license_document(document: object, *, today: date | None = None) -> LicenseState:
    """Verify a parsed license document and classify it (pure, no caching)."""
    if not isinstance(document, dict):
        return _invalid("license document is not a JSON object")
    payload = document.get("payload")
    signature_b64 = document.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature_b64, str):
        return _invalid("license document must contain 'payload' and 'signature'")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        return _invalid("signature is not valid base64")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(license_pubkey.PUBLIC_KEY_HEX))
        public_key.verify(signature, canonical_payload_bytes(payload))
    except (InvalidSignature, ValueError):
        return _invalid("signature verification failed")

    if payload.get("schema") != 1:
        return _invalid("unsupported license schema")
    try:
        expires = date.fromisoformat(str(payload.get("expires_at")))
    except (TypeError, ValueError):
        return _invalid("expires_at must be a YYYY-MM-DD date")
    try:
        max_users = int(payload.get("max_users"))
    except (TypeError, ValueError):
        return _invalid("max_users must be an integer")
    if max_users < 1:
        return _invalid("max_users must be >= 1")
    features_raw = payload.get("features")

    current = today if today is not None else date.today()
    days_left = (expires - current).days  # date-only comparison
    common = {
        "license_id": str(payload.get("license_id") or ""),
        "customer": str(payload.get("customer") or ""),
        "edition": str(payload.get("edition") or ""),
        "expires_at": expires.isoformat(),
        "days_left": days_left,
        "max_users": max_users,
        "features": features_raw if isinstance(features_raw, dict) else {},
    }
    if days_left < 0:
        days_over = -days_left
        if days_over <= settings.LICENSE_GRACE_DAYS:
            return LicenseState(
                state=STATE_GRACE_READONLY,
                reason=f"license expired {days_over} day(s) ago (within {settings.LICENSE_GRACE_DAYS}-day grace)",
                **common,
            )
        return LicenseState(state=STATE_BLOCKED, reason=f"license expired {days_over} day(s) ago", **common)
    if days_left <= settings.LICENSE_EXPIRY_WARN_DAYS:
        return LicenseState(state=STATE_EXPIRING_SOON, reason=f"license expires in {days_left} day(s)", **common)
    return LicenseState(state=STATE_VALID, **common)


def _load_and_verify(path: str) -> LicenseState:
    if not os.path.exists(path):
        return _invalid("license file not found")
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        return _invalid(f"license file unreadable: {exc.__class__.__name__}")
    return verify_license_document(document)


_license_cache_lock = threading.Lock()
_license_state_cache: LicenseState | None = None
_license_cache_path: str | None = None
_license_cache_mtime: float | None = None
_license_cache_checked_at: float = 0.0


def _file_mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def invalidate_license_cache() -> None:
    global _license_state_cache, _license_cache_path, _license_cache_mtime, _license_cache_checked_at
    with _license_cache_lock:
        _license_state_cache = None
        _license_cache_path = None
        _license_cache_mtime = None
        _license_cache_checked_at = 0.0


def get_license_state() -> LicenseState:
    """Return the current license state (cached; re-verifies on mtime/TTL)."""
    if not settings.LICENSE_ENFORCEMENT_ENABLED:
        return LicenseState(state=STATE_UNLICENSED, reason="license enforcement disabled")

    global _license_state_cache, _license_cache_path, _license_cache_mtime, _license_cache_checked_at
    path = license_file_path()
    with _license_cache_lock:
        now = time.monotonic()
        mtime = _file_mtime(path)
        ttl_seconds = settings.LICENSE_RECHECK_INTERVAL_HOURS * 3600.0
        if (
            _license_state_cache is not None
            and _license_cache_path == path
            and _license_cache_mtime == mtime
            and now - _license_cache_checked_at < ttl_seconds
        ):
            return _license_state_cache
        state = _load_and_verify(path)
        if _license_state_cache is None or state.state != _license_state_cache.state:
            logger.info("License state: %s (%s)", state.state, state.reason or state.expires_at)
        _license_state_cache = state
        _license_cache_path = path
        _license_cache_mtime = mtime
        _license_cache_checked_at = now
        return state


def license_feature_enabled(flag: str) -> bool:
    """True when the licensed features grant *flag*.

    Unlicensed (enforcement disabled) grants everything; flags survive the
    read-only grace window; blocked/invalid grant nothing. A flag matches a
    truthy feature value or membership in a list-valued feature, e.g.
    ``features={"industries": ["legal"]}`` enables ``"legal"``.
    """
    state = get_license_state()
    if state.state == STATE_UNLICENSED:
        return True
    if state.state not in _FEATURE_STATES:
        return False
    for value in state.features.values():
        if isinstance(value, list) and flag in value:
            return True
    return bool(state.features.get(flag))


def license_seat_limit() -> int | None:
    """Max user count enforced by a currently-active license (None = no cap)."""
    if not settings.LICENSE_ENFORCEMENT_ENABLED:
        return None
    state = get_license_state()
    if state.state in _ACTIVE_STATES and state.max_users:
        return int(state.max_users)
    return None
