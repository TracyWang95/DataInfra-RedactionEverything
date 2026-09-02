"""Deterministic, tenant-scoped DICOM pseudonym and UID mapping."""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any


def _first(value: Any) -> str:
    if isinstance(value, list | tuple):
        return str(value[0]) if value else ""
    try:
        # pydicom MultiValue is deliberately not imported in this small module.
        if not isinstance(value, str | bytes) and hasattr(value, "__iter__"):
            values = list(value)
            return str(values[0]) if values else ""
    except TypeError:
        pass
    return str(value or "")


@dataclass
class StableDICOMMapper:
    """Stable HMAC mapping without retaining source identifiers.

    The namespace is included in every HMAC message, preventing tokens from
    correlating across tenants or projects even if the same secret is used.
    In-memory caches are an optimisation only; determinism comes from HMAC.
    """

    secret: bytes | str
    namespace: str = "default"
    date_shift_range_days: int = 3650
    _uid_cache: dict[str, str] = field(default_factory=dict, init=False)
    _patient_cache: dict[str, str] = field(default_factory=dict, init=False)
    _token_cache: dict[tuple[str, str], str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if isinstance(self.secret, str):
            self.secret = self.secret.encode("utf-8")
        if len(self.secret) < 16:
            raise ValueError("DICOM mapping secret must contain at least 16 bytes")
        self.namespace = str(self.namespace or "default")
        if self.date_shift_range_days < 1:
            raise ValueError("date_shift_range_days must be positive")

    def _digest(self, purpose: str, value: str) -> bytes:
        message = f"dicom-v1\x1f{self.namespace}\x1f{purpose}\x1f{value}".encode()
        return hmac.new(self.secret, message, hashlib.sha256).digest()

    def fingerprint(self, purpose: str, value: str, *, length: int = 16) -> str:
        return self._digest(purpose, str(value)).hex()[:length]

    def patient_pseudonym(self, source_key: str) -> str:
        key = str(source_key or "NO_PATIENT_KEY")
        if key not in self._patient_cache:
            self._patient_cache[key] = "P-" + self.fingerprint("patient", key, length=20).upper()
        return self._patient_cache[key]

    def token(self, purpose: str, value: str, *, prefix: str = "R", length: int = 20) -> str:
        key = (purpose, str(value or "EMPTY"))
        if key not in self._token_cache:
            self._token_cache[key] = f"{prefix}-{self.fingerprint(purpose, key[1], length=length).upper()}"
        return self._token_cache[key]

    def uid(self, source_uid: str) -> str:
        source = str(source_uid or "")
        if not source:
            return source
        if source not in self._uid_cache:
            # The 2.25 root followed by an unsigned UUID integer is globally
            # valid and stays well below DICOM's 64-character UI limit.
            raw = self._digest("uid", source)[:16]
            self._uid_cache[source] = f"2.25.{uuid.UUID(bytes=raw).int}"
        return self._uid_cache[source]

    def date_shift_days(self, patient_key: str) -> int:
        span = (self.date_shift_range_days * 2) + 1
        offset = int.from_bytes(self._digest("date-shift", patient_key)[:8], "big") % span
        return offset - self.date_shift_range_days

    def shift_da(self, raw: Any, patient_key: str) -> str:
        value = _first(raw).strip()
        if not value:
            return ""
        # The dotted ACR-NEMA form is still encountered in legacy CR objects;
        # accept it as controlled legacy input and always emit current DA form.
        normalized = value.replace(".", "") if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", value) else value
        if not re.fullmatch(r"\d{8}", normalized):
            raise ValueError(f"Unsupported DICOM DA value: {value!r}")
        parsed = datetime.strptime(normalized, "%Y%m%d").date()
        shifted = parsed + timedelta(days=self.date_shift_days(patient_key))
        return shifted.strftime("%Y%m%d")

    def shift_dt(self, raw: Any, patient_key: str) -> str:
        value = _first(raw).strip()
        if not value:
            return ""
        # DT permits reduced precision and optional fractional seconds/timezone.
        match = re.fullmatch(r"(\d{4})(\d{2})?(\d{2})?(.*)", value)
        if not match:
            raise ValueError(f"Unsupported DICOM DT value: {value!r}")
        year, month, day, suffix = match.groups()
        if not month or not day:
            # A year/month-only value cannot be shifted safely without inventing
            # precision; leave it structurally valid but de-identify the year.
            replacement_year = 1900 + (abs(self.date_shift_days(patient_key)) % 100)
            return f"{replacement_year:04d}" + (month or "") + suffix
        parsed = date(int(year), int(month), int(day))
        shifted = parsed + timedelta(days=self.date_shift_days(patient_key))
        return shifted.strftime("%Y%m%d") + suffix

    @property
    def uid_mapping(self) -> dict[str, str]:
        return dict(self._uid_cache)


__all__ = ["StableDICOMMapper"]
