"""Persistent DICOM API workflow and tenant boundary.

This module owns API-facing persistence and deliberately keeps the DICOM
implementation behind four functions exported by :mod:`app.services.dicom`.
It never exposes source filesystem paths or uses source UIDs as public IDs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import uuid
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_OPEN_RISK_STATUSES = frozenset({"open", "unresolved"})
_BLOCKING_SEVERITIES = frozenset({"critical", "high"})
_PIXEL_REVIEW_CODES = frozenset(
    {
        "OVERLAY_NOT_CLEANED",
        "PIXEL_BURNED_IN_REVIEW_REQUIRED",
        "PIXEL_BURNED_IN_STATUS_UNKNOWN",
        "RECOGNIZABLE_VISUAL_FEATURES_REVIEW_REQUIRED",
        "PIXEL_DETECTOR_FINDINGS",
    }
)
logger = logging.getLogger(__name__)


def dicom_pixel_ocr_enabled() -> bool:
    """Return the server-owned DICOM pixel-PHI policy switch (on by default)."""

    return os.environ.get("DICOM_PIXEL_OCR_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


class DicomWorkflowError(Exception):
    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.detail = detail or {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _first(mapping: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        value = mapping.get(name)
        if value is not None and value != "":
            return value
    return default


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _public_json(value: Any) -> Any:
    """Remove local path material recursively before returning engine data."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in {
                "path",
                "paths",
                "file_path",
                "filepath",
                "source_path",
                "output_path",
                "output_paths",
                "output_dir",
                "input_path",
                "input_dir",
                "source_dir",
                "source_sha256",
                "output_sha256",
                "mapping_namespace",
            }:
                continue
            if normalized.endswith("_instance_uid") or normalized in {
                "study_uid",
                "series_uid",
                "sop_uid",
            }:
                continue
            public_key = str(key)
            if os.path.isabs(public_key) or re.match(r"^[A-Za-z]:[\\/]", public_key):
                public_key = "instance-" + hashlib.sha256(
                    public_key.encode("utf-8", errors="replace")
                ).hexdigest()[:12]
            result[public_key] = _public_json(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_public_json(item) for item in value]
    if isinstance(value, Path):
        return value.name
    return value


def _uid(record: dict[str, Any], level: str) -> str:
    if level == "study":
        names = ("study_instance_uid", "StudyInstanceUID", "study_uid", "studyUid", "uid")
    elif level == "series":
        names = ("series_instance_uid", "SeriesInstanceUID", "series_uid", "seriesUid", "uid")
    else:
        names = ("sop_instance_uid", "SOPInstanceUID", "instance_uid", "sop_uid", "uid")
    return str(_first(record, *names, default="") or "")


def _relation_uid(record: dict[str, Any], level: str) -> str:
    if level == "study":
        return str(_first(record, "study_instance_uid", "StudyInstanceUID", "study_uid", "studyUid", default="") or "")
    return str(_first(record, "series_instance_uid", "SeriesInstanceUID", "series_uid", "seriesUid", default="") or "")


class DicomJobService:
    """SQLite-backed DICOM workflow service.

    A connection is opened per operation so FastAPI worker threads do not
    share SQLite connection objects.  Public resource lookups always include
    ``owner_id``; a resource owned by another tenant is indistinguishable from
    a missing resource.
    """

    def __init__(
        self,
        db_path: str | None = None,
        upload_root: str | None = None,
        output_root: str | None = None,
    ) -> None:
        self.db_path = os.path.realpath(db_path or os.path.join(settings.DATA_DIR, "dicom_jobs.sqlite3"))
        self.upload_root = os.path.realpath(upload_root or os.path.join(settings.UPLOAD_DIR, "dicom"))
        self.output_root = os.path.realpath(output_root or os.path.join(settings.OUTPUT_DIR, "dicom"))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.upload_root, exist_ok=True)
        os.makedirs(self.output_root, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_schema(self) -> None:
        with self._schema_lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dicom_ingests (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_dicom_ingests_owner
                    ON dicom_ingests(owner_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS dicom_studies (
                    id TEXT PRIMARY KEY,
                    ingest_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    source_uid TEXT NOT NULL DEFAULT '',
                    subject_key TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    preflight_version INTEGER NOT NULL DEFAULT 1,
                    preflight_completed INTEGER NOT NULL DEFAULT 0,
                    preflight_options_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(ingest_id) REFERENCES dicom_ingests(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dicom_studies_owner
                    ON dicom_studies(owner_id, created_at DESC, id);

                CREATE TABLE IF NOT EXISTS dicom_series (
                    id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    source_uid TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(study_id) REFERENCES dicom_studies(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dicom_series_study
                    ON dicom_series(owner_id, study_id);

                CREATE TABLE IF NOT EXISTS dicom_instances (
                    id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL,
                    series_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    source_uid TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(study_id) REFERENCES dicom_studies(id) ON DELETE CASCADE,
                    FOREIGN KEY(series_id) REFERENCES dicom_series(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dicom_instances_study
                    ON dicom_instances(owner_id, study_id, series_id);

                CREATE TABLE IF NOT EXISTS dicom_risks (
                    id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    review_note TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    source_sop_uid TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(study_id) REFERENCES dicom_studies(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dicom_risks_study
                    ON dicom_risks(owner_id, study_id, status, severity);

                CREATE TABLE IF NOT EXISTS dicom_jobs (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    study_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    options_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    report_json TEXT NOT NULL DEFAULT '{}',
                    output_zip TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    FOREIGN KEY(study_id) REFERENCES dicom_studies(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dicom_jobs_owner
                    ON dicom_jobs(owner_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_dicom_jobs_batch
                    ON dicom_jobs(owner_id, batch_id);

                CREATE TABLE IF NOT EXISTS dicom_idempotency (
                    owner_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(owner_id, endpoint, key)
                );
                """
            )
            # Additive migration for databases created by an earlier DICOM
            # development build.  Source associations stay internal and are
            # required to translate per-instance review decisions safely.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(dicom_risks)").fetchall()}
            if "source_path" not in columns:
                conn.execute("ALTER TABLE dicom_risks ADD COLUMN source_path TEXT NOT NULL DEFAULT ''")
            if "source_sop_uid" not in columns:
                conn.execute("ALTER TABLE dicom_risks ADD COLUMN source_sop_uid TEXT NOT NULL DEFAULT ''")
            study_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(dicom_studies)").fetchall()
            }
            if "preflight_completed" not in study_columns:
                conn.execute(
                    "ALTER TABLE dicom_studies ADD COLUMN preflight_completed INTEGER NOT NULL DEFAULT 0"
                )
                conn.execute(
                    "UPDATE dicom_studies SET preflight_completed=1 WHERE preflight_version>1"
                )
            if "preflight_options_json" not in study_columns:
                conn.execute(
                    "ALTER TABLE dicom_studies ADD COLUMN preflight_options_json TEXT NOT NULL DEFAULT '{}'"
                )

    @staticmethod
    def tenant_key(owner_id: str) -> str:
        return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]

    def _core_options(self, owner_id: str, options: dict[str, Any]) -> dict[str, Any]:
        """Inject server-owned mapping scope; clients cannot override it."""
        result = dict(options)
        result.pop("tenant_id", None)
        result.pop("mapping_namespace", None)
        result.pop("mapping_secret", None)
        result.pop("pixel_review_decisions", None)
        result.pop("pixel_ocr_required", None)
        result["mapping_namespace"] = f"tenant-{self.tenant_key(owner_id)}"
        pixel_ocr_enabled = dicom_pixel_ocr_enabled()
        result["pixel_ocr_required"] = pixel_ocr_enabled
        if pixel_ocr_enabled:
            # This is a server privacy invariant, not a client preference: a
            # caller cannot opt out of detecting and masking burned-in PHI.
            result["clean_pixel_data"] = True
        return result

    def claim_idempotency(
        self,
        *,
        owner_id: str,
        endpoint: str,
        key: str | None,
        request_hash: str,
    ) -> dict[str, Any] | None:
        if not key:
            return None
        if not _IDEMPOTENCY_KEY_RE.fullmatch(key):
            raise DicomWorkflowError(400, "INVALID_IDEMPOTENCY_KEY", "无效的幂等键")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_hash, response_json FROM dicom_idempotency "
                "WHERE owner_id=? AND endpoint=? AND key=?",
                (owner_id, endpoint, key),
            ).fetchone()
            if row:
                if row["request_hash"] != request_hash:
                    raise DicomWorkflowError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "同一幂等键不能用于不同请求",
                    )
                if not row["response_json"]:
                    raise DicomWorkflowError(
                        409,
                        "IDEMPOTENCY_IN_PROGRESS",
                        "相同请求正在处理中，请稍后重试",
                    )
                return _loads(row["response_json"], {})
            conn.execute(
                "INSERT INTO dicom_idempotency(owner_id, endpoint, key, request_hash, response_json, created_at) "
                "VALUES(?,?,?,?,NULL,?)",
                (owner_id, endpoint, key, request_hash, _now()),
            )
        return None

    def complete_idempotency(
        self, *, owner_id: str, endpoint: str, key: str | None, response: dict[str, Any]
    ) -> None:
        if not key:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE dicom_idempotency SET response_json=? "
                "WHERE owner_id=? AND endpoint=? AND key=?",
                (_json(response), owner_id, endpoint, key),
            )

    def release_idempotency(self, *, owner_id: str, endpoint: str, key: str | None) -> None:
        if not key:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM dicom_idempotency WHERE owner_id=? AND endpoint=? AND key=? "
                "AND response_json IS NULL",
                (owner_id, endpoint, key),
            )

    @staticmethod
    def _core():
        from app.services import dicom

        return dicom

    def _safe_source_path(self, value: Any, allowed_root: str, fallback_paths: list[str]) -> str:
        candidate = os.path.realpath(os.fspath(value)) if value else ""
        if candidate:
            try:
                if os.path.commonpath((candidate, allowed_root)) == allowed_root and os.path.isfile(candidate):
                    return candidate
            except ValueError:
                pass
        if len(fallback_paths) == 1:
            return fallback_paths[0]
        raise DicomWorkflowError(
            422,
            "DICOM_MANIFEST_INVALID",
            "DICOM核心返回了无效的实例路径",
        )

    def ingest_paths(
        self,
        *,
        owner_id: str,
        entries: list[tuple[str, str]],
        profile: str,
        options: dict[str, Any],
        source_kind: str,
    ) -> dict[str, Any]:
        if not entries:
            raise DicomWorkflowError(400, "DICOM_EMPTY_UPLOAD", "没有可处理的DICOM文件")

        ingest_id = str(uuid.uuid4())
        tenant_root = os.path.join(self.upload_root, self.tenant_key(owner_id))
        input_root = os.path.realpath(os.path.join(tenant_root, ingest_id, "input"))
        os.makedirs(input_root, exist_ok=False)
        final_paths: list[str] = []
        try:
            seen: set[str] = set()
            for source_path, relative_name in entries:
                relative_key = relative_name.casefold()
                if relative_key in seen:
                    raise DicomWorkflowError(
                        400,
                        "DICOM_DUPLICATE_PATH",
                        "上传内容包含重复路径",
                        {"path": relative_name},
                    )
                seen.add(relative_key)
                destination = os.path.realpath(os.path.join(input_root, *relative_name.split("/")))
                try:
                    inside = os.path.commonpath((destination, input_root)) == input_root
                except ValueError:
                    inside = False
                if not inside:
                    raise DicomWorkflowError(400, "DICOM_UNSAFE_PATH", "上传路径不安全")
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.move(source_path, destination)
                final_paths.append(destination)

            try:
                manifest = self._core().inspect_dicom_paths(
                    final_paths,
                    profile=profile,
                    options=self._core_options(owner_id, options),
                )
            except DicomWorkflowError:
                raise
            except Exception as exc:
                raise DicomWorkflowError(
                    422,
                    "DICOM_INSPECTION_FAILED",
                    "无法解析上传的DICOM对象",
                    {"failure_type": type(exc).__name__},
                ) from exc
            if not isinstance(manifest, dict):
                raise DicomWorkflowError(422, "DICOM_MANIFEST_INVALID", "DICOM解析结果无效")

            response = self._persist_manifest(
                owner_id=owner_id,
                ingest_id=ingest_id,
                profile=profile,
                source_kind=source_kind,
                input_root=input_root,
                final_paths=final_paths,
                manifest=manifest,
            )
            return response
        except Exception:
            shutil.rmtree(os.path.dirname(input_root), ignore_errors=True)
            raise

    def _persist_manifest(
        self,
        *,
        owner_id: str,
        ingest_id: str,
        profile: str,
        source_kind: str,
        input_root: str,
        final_paths: list[str],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        studies = [item for item in _as_list(manifest.get("studies")) if isinstance(item, dict)]
        flat_series = [item for item in _as_list(manifest.get("series")) if isinstance(item, dict)]
        flat_instances = [item for item in _as_list(manifest.get("instances")) if isinstance(item, dict)]
        flat_risks = [item for item in _as_list(manifest.get("risks")) if isinstance(item, dict)]

        if not studies and flat_instances:
            grouped: dict[str, dict[str, Any]] = {}
            for instance in flat_instances:
                study_uid = _relation_uid(instance, "study") or "single-study"
                grouped.setdefault(study_uid, {"study_instance_uid": study_uid})
            studies = list(grouped.values())
        if not studies:
            raise DicomWorkflowError(
                422,
                "DICOM_NO_STUDIES",
                "上传内容中未发现可处理的DICOM检查",
            )

        created_at = _now()
        public_studies: list[dict[str, Any]] = []
        total_series = 0
        total_instances = 0
        total_risks = 0

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO dicom_ingests(id,owner_id,profile,source_kind,created_at,payload_json) "
                "VALUES(?,?,?,?,?,?)",
                (
                    ingest_id,
                    owner_id,
                    profile,
                    source_kind,
                    created_at,
                    _json(_public_json({k: v for k, v in manifest.items() if k not in {"studies", "series", "instances", "risks"}})),
                ),
            )

            for study_index, study in enumerate(studies):
                source_study_uid = _uid(study, "study")
                study_id = str(uuid.uuid4())
                subject_seed = source_study_uid or f"{ingest_id}:{study_index}"
                subject_key = "SUBJ-" + hashlib.sha256(
                    f"{owner_id}\0{subject_seed}".encode()
                ).hexdigest()[:12].upper()

                nested_series = [item for item in _as_list(study.get("series")) if isinstance(item, dict)]
                relevant_series = nested_series or [
                    item
                    for item in flat_series
                    if not source_study_uid or _relation_uid(item, "study") == source_study_uid
                ]
                if not relevant_series:
                    relevant_instances = [
                        item
                        for item in flat_instances
                        if not source_study_uid or _relation_uid(item, "study") == source_study_uid
                    ]
                    if relevant_instances:
                        grouped_series: dict[str, dict[str, Any]] = {}
                        for item in relevant_instances:
                            series_uid = _relation_uid(item, "series") or "single-series"
                            group = grouped_series.setdefault(
                                series_uid,
                                {"series_instance_uid": series_uid, "instances": []},
                            )
                            group["instances"].append(item)
                        relevant_series = list(grouped_series.values())

                study_status = "review_required" if flat_risks else "preflight_ready"
                conn.execute(
                    "INSERT INTO dicom_studies(id,ingest_id,owner_id,source_uid,subject_key,profile,status,"
                    "preflight_version,created_at,updated_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        study_id,
                        ingest_id,
                        owner_id,
                        source_study_uid,
                        subject_key,
                        profile,
                        study_status,
                        1,
                        created_at,
                        created_at,
                        _json(study),
                    ),
                )

                public_series: list[dict[str, Any]] = []
                for series in relevant_series:
                    source_series_uid = _uid(series, "series")
                    series_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO dicom_series(id,study_id,owner_id,source_uid,payload_json) VALUES(?,?,?,?,?)",
                        (series_id, study_id, owner_id, source_series_uid, _json(series)),
                    )
                    nested_instances = [item for item in _as_list(series.get("instances")) if isinstance(item, dict)]
                    relevant_instances = nested_instances or [
                        item
                        for item in flat_instances
                        if (not source_study_uid or _relation_uid(item, "study") == source_study_uid)
                        and (not source_series_uid or _relation_uid(item, "series") == source_series_uid)
                    ]
                    public_instances: list[dict[str, Any]] = []
                    for instance in relevant_instances:
                        instance_id = str(uuid.uuid4())
                        source_path = self._safe_source_path(
                            _first(instance, "path", "file_path", "source_path"),
                            input_root,
                            final_paths,
                        )
                        conn.execute(
                            "INSERT INTO dicom_instances(id,study_id,series_id,owner_id,source_uid,source_path,payload_json) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (
                                instance_id,
                                study_id,
                                series_id,
                                owner_id,
                                _uid(instance, "instance"),
                                source_path,
                                _json(instance),
                            ),
                        )
                        public_instances.append(self._public_instance(instance_id, series_id, instance))
                    total_instances += len(public_instances)
                    total_series += 1
                    public_series.append(self._public_series(series_id, series, public_instances))

                relevant_risks = [
                    item
                    for item in flat_risks
                    if not _relation_uid(item, "study")
                    or not source_study_uid
                    or _relation_uid(item, "study") == source_study_uid
                ]
                nested_risks = [item for item in _as_list(study.get("risks")) if isinstance(item, dict)]
                if nested_risks:
                    relevant_risks.extend(nested_risks)
                risk_count = self._insert_risks(conn, owner_id, study_id, relevant_risks)
                total_risks += risk_count
                study_status = "review_required" if risk_count else "preflight_ready"
                conn.execute(
                    "UPDATE dicom_studies SET status=? WHERE id=?",
                    (study_status, study_id),
                )
                public_studies.append(
                    self._public_study(
                        study_id=study_id,
                        ingest_id=ingest_id,
                        subject_key=subject_key,
                        profile=profile,
                        status=study_status,
                        preflight_version=1,
                        created_at=created_at,
                        payload=study,
                        series=public_series,
                        risk_count=risk_count,
                    )
                )

        with self._connect() as conn:
            ingest_risk_rows = conn.execute(
                "SELECT severity,status FROM dicom_risks WHERE owner_id=? AND study_id IN "
                "(SELECT id FROM dicom_studies WHERE ingest_id=? AND owner_id=?)",
                (owner_id, ingest_id, owner_id),
            ).fetchall()
        ingest_risk_summary = self._risk_summary([dict(row) for row in ingest_risk_rows])
        for public_study in public_studies:
            public_study["risk_summary"] = self.risks(public_study["id"], owner_id)["summary"]
        return {
            "ingest_id": ingest_id,
            "profile": profile,
            "source_kind": source_kind,
            "study_count": len(public_studies),
            "series_count": total_series,
            "instance_count": total_instances,
            "studies": public_studies,
            "risks_summary": ingest_risk_summary,
            "created_at": created_at,
        }

    def _insert_risks(
        self,
        conn: sqlite3.Connection,
        owner_id: str,
        study_id: str,
        risks: Iterable[dict[str, Any]],
    ) -> int:
        count = 0
        seen: set[str] = set()
        for risk in risks:
            code = str(_first(risk, "code", "risk_code", "type", default="DICOM_RISK"))[:128]
            severity = str(_first(risk, "severity", "level", default="medium")).lower()
            severity = {"blocking": "critical", "warning": "medium"}.get(severity, severity)
            if severity not in {"critical", "high", "medium", "low", "info"}:
                severity = "medium"
            category = str(_first(risk, "category", "kind", default="metadata"))[:128]
            message = str(_first(risk, "message", "description", "reason", default=code))[:2000]
            details = _public_json(_first(risk, "details", "metadata", default={}))
            source_path = str(_first(risk, "path", "source_path", default="") or "")
            source_sop_uid = str(
                _first(risk, "sop_instance_uid", "SOPInstanceUID", "sop_uid", default="") or ""
            )
            fingerprint = _json(
                [code, severity, category, message, details, source_path, source_sop_uid]
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            conn.execute(
                "INSERT INTO dicom_risks(id,study_id,owner_id,code,category,severity,status,message,details_json,"
                "source_path,source_sop_uid) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    study_id,
                    owner_id,
                    code,
                    category,
                    severity,
                    "open",
                    message,
                    _json(details),
                    source_path,
                    source_sop_uid,
                ),
            )
            count += 1
        return count

    @staticmethod
    def _public_instance(instance_id: str, series_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": instance_id,
            "instance_id": instance_id,
            "series_id": series_id,
            "instance_number": _first(payload, "instance_number", "InstanceNumber"),
            "sop_class_uid": _first(payload, "sop_class_uid", "SOPClassUID"),
            "transfer_syntax_uid": _first(payload, "transfer_syntax_uid", "TransferSyntaxUID"),
            "frame_count": int(_first(payload, "frame_count", "number_of_frames", "NumberOfFrames", default=1) or 1),
            "rows": _first(payload, "rows", "Rows"),
            "columns": _first(payload, "columns", "Columns"),
            "previewable": bool(_first(payload, "previewable", default=True)),
            "preview_available": bool(_first(payload, "previewable", default=True)),
        }

    @classmethod
    def _public_series(
        cls, series_id: str, payload: dict[str, Any], instances: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {
            "id": series_id,
            "series_id": series_id,
            "modality": _first(payload, "modality", "Modality"),
            "series_number": _first(payload, "series_number", "SeriesNumber"),
            "instance_count": len(instances),
            "instances": instances,
        }

    @staticmethod
    def _public_study(
        *,
        study_id: str,
        ingest_id: str,
        subject_key: str,
        profile: str,
        status: str,
        preflight_version: int,
        created_at: str,
        payload: dict[str, Any],
        series: list[dict[str, Any]],
        risk_count: int,
    ) -> dict[str, Any]:
        modalities = _first(payload, "modalities", "modalities_in_study", "ModalitiesInStudy")
        if isinstance(modalities, str):
            modalities = [item for item in modalities.replace("\\", ",").split(",") if item]
        if not modalities:
            modalities = sorted({str(item["modality"]) for item in series if item.get("modality")})
        return {
            "id": study_id,
            "study_id": study_id,
            "ingest_id": ingest_id,
            "subject_key": subject_key,
            "patient_pseudonym": subject_key,
            "profile": profile,
            "status": status,
            "preflight_version": preflight_version,
            "modalities": modalities or [],
            "series_count": len(series),
            "instance_count": sum(int(item.get("instance_count") or 0) for item in series),
            "risk_count": risk_count,
            "risk_summary": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
                "unresolved": risk_count,
                "blocking": 0,
                "total": risk_count,
            },
            "created_at": created_at,
            "series": series,
        }

    def _study_row(self, study_id: str, owner_id: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dicom_studies WHERE id=? AND owner_id=?",
                (study_id, owner_id),
            ).fetchone()
        if not row:
            raise DicomWorkflowError(404, "DICOM_STUDY_NOT_FOUND", "DICOM检查不存在")
        return row

    def list_studies(
        self,
        *,
        owner_id: str,
        status: str | None = None,
        modality: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        clauses = ["owner_id=?"]
        params: list[Any] = [owner_id]
        if status:
            clauses.append("status=?")
            params.append(status)
        query = "SELECT * FROM dicom_studies WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC,id LIMIT ? OFFSET ?"
        params.extend([limit + 1, offset])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        items = [self._study_from_row(row, include_instances=False) for row in rows[:limit]]
        if modality:
            modality_upper = modality.upper()
            items = [item for item in items if modality_upper in {str(v).upper() for v in item["modalities"]}]
        return {
            "items": items,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if len(rows) > limit else None,
        }

    def _study_from_row(self, row: sqlite3.Row, *, include_instances: bool) -> dict[str, Any]:
        payload = _loads(row["payload_json"], {})
        with self._connect() as conn:
            series_rows = conn.execute(
                "SELECT * FROM dicom_series WHERE study_id=? AND owner_id=? ORDER BY id",
                (row["id"], row["owner_id"]),
            ).fetchall()
            risk_count = conn.execute(
                "SELECT COUNT(*) FROM dicom_risks WHERE study_id=? AND owner_id=?",
                (row["id"], row["owner_id"]),
            ).fetchone()[0]
            latest_job_row = conn.execute(
                "SELECT * FROM dicom_jobs WHERE study_id=? AND owner_id=? "
                "ORDER BY created_at DESC,id DESC LIMIT 1",
                (row["id"], row["owner_id"]),
            ).fetchone()
            public_series: list[dict[str, Any]] = []
            for series_row in series_rows:
                instance_rows = conn.execute(
                    "SELECT * FROM dicom_instances WHERE series_id=? AND owner_id=? ORDER BY id",
                    (series_row["id"], row["owner_id"]),
                ).fetchall()
                instances = [
                    self._public_instance(
                        instance_row["id"],
                        series_row["id"],
                        _loads(instance_row["payload_json"], {}),
                    )
                    for instance_row in instance_rows
                ]
                item = self._public_series(
                    series_row["id"], _loads(series_row["payload_json"], {}), instances
                )
                if not include_instances:
                    item.pop("instances", None)
                public_series.append(item)
        result = self._public_study(
            study_id=row["id"],
            ingest_id=row["ingest_id"],
            subject_key=row["subject_key"],
            profile=row["profile"],
            status=row["status"],
            preflight_version=int(row["preflight_version"]),
            created_at=row["created_at"],
            payload=payload,
            series=public_series,
            risk_count=int(risk_count),
        )
        result["risk_summary"] = self.risks(row["id"], row["owner_id"])["summary"]
        if latest_job_row is not None:
            result["latest_job"] = self._public_job(latest_job_row)
        return result

    def get_study(self, study_id: str, owner_id: str) -> dict[str, Any]:
        return self._study_from_row(self._study_row(study_id, owner_id), include_instances=True)

    def study_paths(self, study_id: str, owner_id: str) -> list[str]:
        self._study_row(study_id, owner_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source_path FROM dicom_instances WHERE study_id=? AND owner_id=? ORDER BY id",
                (study_id, owner_id),
            ).fetchall()
        paths = [str(row["source_path"]) for row in rows if os.path.isfile(row["source_path"])]
        if not paths:
            raise DicomWorkflowError(409, "DICOM_SOURCE_MISSING", "DICOM源实例不可用")
        return paths

    def metadata(
        self,
        study_id: str,
        owner_id: str,
        *,
        series_id: str | None = None,
        instance_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        study = self._study_row(study_id, owner_id)
        clauses = ["study_id=?", "owner_id=?"]
        params: list[Any] = [study_id, owner_id]
        if series_id:
            clauses.append("series_id=?")
            params.append(series_id)
        if instance_id:
            clauses.append("id=?")
            params.append(instance_id)
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM dicom_instances WHERE " + " AND ".join(clauses), params
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT id,series_id,source_path,payload_json FROM dicom_instances WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        if (series_id or instance_id) and not rows:
            raise DicomWorkflowError(404, "DICOM_INSTANCE_NOT_FOUND", "DICOM序列或实例不存在")
        study_payload = _loads(study["payload_json"], {})
        entries: list[dict[str, Any]] = []
        for row in rows:
            payload = _loads(row["payload_json"], {})
            embedded = _first(payload, "metadata", "tags", "attributes", default={})
            if embedded:
                entries.extend(self._embedded_metadata_entries(embedded))
            else:
                entries.extend(self._source_metadata_entries(row["source_path"], study["profile"]))
            if len(entries) >= limit:
                entries = entries[:limit]
                break
        return {
            "study_id": study_id,
            "preflight_version": int(study["preflight_version"]),
            "study_metadata": _public_json(
                _first(study_payload, "metadata", "tags", "attributes", default={})
            ),
            "instances": [
                {
                    "id": row["id"],
                    "series_id": row["series_id"],
                    "metadata": _public_json(
                        _first(
                            _loads(row["payload_json"], {}),
                            "metadata",
                            "tags",
                            "attributes",
                            default={},
                        )
                    ),
                }
                for row in rows
            ],
            "entries": entries,
            "total": int(total),
            "offset": offset,
            "limit": limit,
        }

    @staticmethod
    def _embedded_metadata_entries(metadata: Any) -> list[dict[str, Any]]:
        if isinstance(metadata, list):
            return [dict(item) for item in metadata if isinstance(item, dict)]
        if not isinstance(metadata, dict):
            return []
        entries: list[dict[str, Any]] = []
        for tag, item in metadata.items():
            value = item if isinstance(item, dict) else {"value": item}
            original = value.get("original_value", value.get("value"))
            entries.append(
                {
                    "tag": str(value.get("tag") or tag),
                    "keyword": value.get("keyword"),
                    "vr": value.get("vr"),
                    "original_value": None if original is None else str(original)[:500],
                    "output_value": value.get("output_value"),
                    "action": str(value.get("action") or "review"),
                    "risk_level": value.get("risk_level"),
                    "source": str(value.get("source") or "dataset"),
                }
            )
        return entries

    @staticmethod
    def _source_metadata_entries(path: str, profile: str) -> list[dict[str, Any]]:
        """Build a bounded, pixel-free tag review table from a source instance."""
        try:
            from app.services.dicom.policy import build_policy
            from app.services.dicom.reader import read_dataset

            profile_alias = {
                "research_strict": "strict",
                "ai_training": "strict",
                "longitudinal_research": "longitudinal",
                "internal_pseudonymized": "basic",
            }.get(profile, profile)
            policy = build_policy(profile_alias)
            rules: dict[str, str] = {}
            for rule in policy.rules:
                rules[rule.selector.lower().replace("(", "").replace(")", "").replace(" ", "")] = rule.action.value
            dataset = read_dataset(path, stop_before_pixels=True)
        except Exception:
            return []

        output: list[dict[str, Any]] = []

        def walk(current: Any, source: str = "dataset", prefix: str = "") -> None:
            for element in current:
                tag = f"{element.tag.group:04X},{element.tag.element:04X}"
                tag_path = f"{prefix}/{tag}" if prefix else tag
                keyword = element.keyword or ""
                lookup = tag.lower()
                action = rules.get(keyword.lower()) or rules.get(lookup) or "K"
                if element.tag.is_private and policy.remove_private_tags:
                    action = "X"
                elif action == "K" and element.VR in {"DA", "DT"}:
                    action = "C" if policy.retain_longitudinal_dates else "Z"
                elif action == "K" and element.VR == "UI" and not keyword.endswith("SOPClassUID"):
                    action = "U"
                if element.VR == "SQ":
                    display = f"<{len(element.value or [])} item(s)>"
                elif isinstance(element.value, bytes):
                    display = f"<{len(element.value)} bytes>"
                else:
                    display = str(element.value or "")[:500]
                if action == "X":
                    predicted: str | None = None
                elif action == "Z":
                    predicted = ""
                elif action in {"D", "U", "C"}:
                    predicted = "<generated during de-identification>"
                else:
                    predicted = display
                output.append(
                    {
                        "tag": tag_path,
                        "keyword": keyword,
                        "vr": element.VR,
                        "original_value": display,
                        "output_value": predicted,
                        "action": action,
                        "risk_level": "high" if keyword in {"PatientName", "PatientID", "AccessionNumber"} else None,
                        "source": source,
                    }
                )
                if element.VR == "SQ":
                    for index, item in enumerate(element.value or []):
                        walk(item, source, f"{tag_path}[{index}]")

        file_meta = getattr(dataset, "file_meta", None)
        if file_meta is not None:
            walk(file_meta, "file_meta")
        walk(dataset)
        return output

    def risks(self, study_id: str, owner_id: str) -> dict[str, Any]:
        self._study_row(study_id, owner_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dicom_risks WHERE study_id=? AND owner_id=? "
                "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
                "WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,id",
                (study_id, owner_id),
            ).fetchall()
            instance_rows = conn.execute(
                "SELECT id,source_path,source_uid FROM dicom_instances WHERE study_id=? AND owner_id=?",
                (study_id, owner_id),
            ).fetchall()
        instance_by_path = {str(row["source_path"]): row["id"] for row in instance_rows}
        instance_by_sop = {str(row["source_uid"]): row["id"] for row in instance_rows if row["source_uid"]}
        items = [
            {
                "id": row["id"],
                "risk_id": row["id"],
                "study_id": study_id,
                "code": row["code"],
                "category": row["category"],
                "severity": row["severity"],
                "status": row["status"],
                "message": row["message"],
                "details": _loads(row["details_json"], {}),
                "tag": _loads(row["details_json"], {}).get("tag"),
                "keyword": _loads(row["details_json"], {}).get("keyword"),
                "value_preview": _loads(row["details_json"], {}).get("value_preview"),
                "instance_id": instance_by_path.get(str(row["source_path"]))
                or instance_by_sop.get(str(row["source_sop_uid"])),
                "reviewed_by": row["reviewed_by"],
                "reviewed_at": row["reviewed_at"],
                "review_note": row["review_note"],
            }
            for row in rows
        ]
        return {
            "study_id": study_id,
            "items": items,
            "risks": items,
            "summary": self._risk_summary(items),
        }

    @staticmethod
    def _risk_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        by_severity = {name: 0 for name in ("critical", "high", "medium", "low", "info")}
        open_count = 0
        blocking = 0
        for item in items:
            severity = str(item.get("severity") or "medium")
            by_severity[severity] = by_severity.get(severity, 0) + 1
            is_open = item.get("status") in _OPEN_RISK_STATUSES
            is_accepted_blocking = (
                item.get("status") == "accepted" and severity in _BLOCKING_SEVERITIES
            )
            if is_open or is_accepted_blocking:
                open_count += 1
                if severity in _BLOCKING_SEVERITIES:
                    blocking += 1
        return {
            "total": len(items),
            "open": open_count,
            "unresolved": open_count,
            "blocking": blocking,
            "by_severity": by_severity,
            **by_severity,
        }

    def preflight(
        self,
        *,
        study_id: str,
        owner_id: str,
        profile: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        row = self._study_row(study_id, owner_id)
        paths = self.study_paths(study_id, owner_id)
        try:
            result = self._core().preflight_study(
                paths,
                profile=profile,
                options=self._core_options(owner_id, options),
            )
        except Exception as exc:
            raise DicomWorkflowError(
                422,
                "DICOM_PREFLIGHT_FAILED",
                "DICOM策略预检失败",
                {"failure_type": type(exc).__name__},
            ) from exc
        if not isinstance(result, dict):
            raise DicomWorkflowError(422, "DICOM_PREFLIGHT_INVALID", "DICOM预检结果无效")
        risks = [item for item in _as_list(result.get("risks")) if isinstance(item, dict)]
        version = int(row["preflight_version"]) + 1
        status = "review_required" if risks else "preflight_ready"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM dicom_risks WHERE study_id=? AND owner_id=?",
                (study_id, owner_id),
            )
            self._insert_risks(conn, owner_id, study_id, risks)
            conn.execute(
                "UPDATE dicom_studies SET profile=?,status=?,preflight_version=?,"
                "preflight_completed=1,preflight_options_json=?,updated_at=? "
                "WHERE id=? AND owner_id=?",
                (profile, status, version, _json(options), _now(), study_id, owner_id),
            )
        risk_data = self.risks(study_id, owner_id)
        return {
            "study_id": study_id,
            "profile": profile,
            "options": options,
            "status": status,
            "preflight_version": version,
            "risks": risk_data["items"],
            "risks_summary": risk_data["summary"],
            "risk_summary": risk_data["summary"],
            "export_allowed": risk_data["summary"]["blocking"] == 0,
            "planned_actions": _public_json(result.get("planned_actions") or result.get("action_counts") or {}),
            "result": _public_json({k: v for k, v in result.items() if k != "risks"}),
        }

    def review(
        self,
        *,
        study_id: str,
        owner_id: str,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._study_row(study_id, owner_id)
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for decision in decisions:
                row = conn.execute(
                    "SELECT severity FROM dicom_risks WHERE id=? AND study_id=? AND owner_id=?",
                    (decision["risk_id"], study_id, owner_id),
                ).fetchone()
                if not row:
                    raise DicomWorkflowError(404, "DICOM_RISK_NOT_FOUND", "DICOM风险项不存在")
                if (
                    decision["resolution"] == "accepted"
                    and row["severity"] in _BLOCKING_SEVERITIES
                    and len(str(decision.get("note") or "").strip()) < 10
                ):
                    raise DicomWorkflowError(
                        400,
                        "DICOM_REVIEW_NOTE_REQUIRED",
                        "接受高风险项必须填写至少10个字符的理由",
                        {"risk_id": decision["risk_id"]},
                    )
                mapped_status = {
                    "resolved": "resolved",
                    "false_positive": "dismissed",
                    "accepted": "accepted",
                }[decision["resolution"]]
                conn.execute(
                    "UPDATE dicom_risks SET status=?,reviewed_by=?,reviewed_at=?,review_note=? "
                    "WHERE id=? AND study_id=? AND owner_id=?",
                    (
                        mapped_status,
                        owner_id,
                        now,
                        str(decision.get("note") or ""),
                        decision["risk_id"],
                        study_id,
                        owner_id,
                    ),
                )
            open_count = conn.execute(
                "SELECT COUNT(*) FROM dicom_risks WHERE study_id=? AND owner_id=? AND "
                "(status IN ('open','unresolved') OR (status='accepted' AND severity IN ('critical','high')))",
                (study_id, owner_id),
            ).fetchone()[0]
            status = "review_required" if open_count else "ready"
            conn.execute(
                "UPDATE dicom_studies SET status=?,updated_at=? WHERE id=? AND owner_id=?",
                (status, now, study_id, owner_id),
            )
        risk_data = self.risks(study_id, owner_id)
        return {
            "study_id": study_id,
            "status": status,
            **risk_data,
            "risk_summary": risk_data["summary"],
            "export_allowed": risk_data["summary"]["blocking"] == 0,
        }

    def preview(
        self,
        *,
        study_id: str,
        instance_id: str,
        owner_id: str,
        frame_index: int,
        window_center: float | None,
        window_width: float | None,
    ) -> bytes:
        self._study_row(study_id, owner_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_path,payload_json FROM dicom_instances "
                "WHERE id=? AND study_id=? AND owner_id=?",
                (instance_id, study_id, owner_id),
            ).fetchone()
        if not row:
            raise DicomWorkflowError(404, "DICOM_INSTANCE_NOT_FOUND", "DICOM实例不存在")
        instance_payload = _loads(row["payload_json"], {})
        frame_count = max(
            1,
            int(
                _first(
                    instance_payload,
                    "frame_count",
                    "number_of_frames",
                    "NumberOfFrames",
                    default=1,
                )
                or 1
            ),
        )
        if frame_index >= frame_count:
            raise DicomWorkflowError(
                422,
                "DICOM_FRAME_OUT_OF_RANGE",
                "DICOM帧索引超出有效范围",
                {"frame": frame_index, "frame_count": frame_count},
            )
        try:
            return self._core().render_instance_preview(
                row["source_path"],
                frame_index=frame_index,
                window_center=window_center,
                window_width=window_width,
            )
        except IndexError as exc:
            raise DicomWorkflowError(
                422,
                "DICOM_FRAME_OUT_OF_RANGE",
                "DICOM帧索引超出有效范围",
                {"frame": frame_index, "frame_count": frame_count},
            ) from exc
        except Exception as exc:
            code = "DICOM_PIXEL_DECODE_UNAVAILABLE" if exc.__class__.__name__ == "DicomPixelDecodeError" else "DICOM_PREVIEW_FAILED"
            status = 422 if code == "DICOM_PIXEL_DECODE_UNAVAILABLE" else 500
            raise DicomWorkflowError(
                status,
                code,
                "DICOM像素数据无法预览" if status == 422 else "DICOM预览生成失败",
                {"failure_type": type(exc).__name__},
            ) from exc

    def _validate_job_request(
        self,
        study_id: str,
        owner_id: str,
        expected_preflight_version: int,
        profile: str,
        options: dict[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> sqlite3.Row:
        if conn is None:
            with self._connect() as owned_conn:
                return self._validate_job_request(
                    study_id,
                    owner_id,
                    expected_preflight_version,
                    profile,
                    options,
                    conn=owned_conn,
                )
        row = conn.execute(
            "SELECT * FROM dicom_studies WHERE id=? AND owner_id=?",
            (study_id, owner_id),
        ).fetchone()
        if not row:
            raise DicomWorkflowError(404, "DICOM_STUDY_NOT_FOUND", "DICOM检查不存在")
        if not bool(row["preflight_completed"]):
            raise DicomWorkflowError(
                409,
                "DICOM_PREFLIGHT_REQUIRED",
                "执行去标识化前必须完成风险预检",
            )
        if int(row["preflight_version"]) != expected_preflight_version:
            raise DicomWorkflowError(
                409,
                "DICOM_PREFLIGHT_STALE",
                "预检结果已更新，请刷新后重试",
                {"current_version": int(row["preflight_version"])},
            )
        if str(row["profile"]) != profile:
            raise DicomWorkflowError(
                409,
                "DICOM_PREFLIGHT_PROFILE_MISMATCH",
                "去标识化策略与已完成的预检策略不一致",
                {"preflight_profile": str(row["profile"]), "requested_profile": profile},
            )
        if _loads(row["preflight_options_json"], {}) != options:
            raise DicomWorkflowError(
                409,
                "DICOM_PREFLIGHT_OPTIONS_MISMATCH",
                "去标识化选项与已完成的预检选项不一致",
            )
        active = conn.execute(
            "SELECT id FROM dicom_jobs WHERE study_id=? AND owner_id=? AND status IN ('queued','running')",
            (study_id, owner_id),
        ).fetchone()
        if active:
            raise DicomWorkflowError(
                409,
                "DICOM_JOB_ACTIVE",
                "该检查已有执行中的匿名化任务",
                {"job_id": active["id"]},
            )
        return row

    def create_job(
        self,
        *,
        study_id: str,
        owner_id: str,
        profile: str,
        options: dict[str, Any],
        expected_preflight_version: int,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_job_request(
                study_id,
                owner_id,
                expected_preflight_version,
                profile,
                options,
                conn=conn,
            )
            conn.execute(
                "INSERT INTO dicom_jobs(id,batch_id,study_id,owner_id,profile,options_json,status,progress,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?, 'queued',0,?,?)",
                (job_id, batch_id, study_id, owner_id, profile, _json(options), now, now),
            )
            conn.execute(
                "UPDATE dicom_studies SET status='queued',updated_at=? WHERE id=? AND owner_id=?",
                (now, study_id, owner_id),
            )
        return self.get_job(job_id, owner_id)

    def create_batch_jobs(
        self,
        *,
        study_ids: list[str],
        owner_id: str,
        profile: str,
        options: dict[str, Any],
        expected_versions: dict[str, int],
    ) -> dict[str, Any]:
        batch_id = str(uuid.uuid4())
        now = _now()
        job_ids: list[str] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for study_id in study_ids:
                self._validate_job_request(
                    study_id,
                    owner_id,
                    expected_versions[study_id],
                    profile,
                    options,
                    conn=conn,
                )
            for study_id in study_ids:
                job_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO dicom_jobs(id,batch_id,study_id,owner_id,profile,options_json,status,progress,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?, 'queued',0,?,?)",
                    (
                        job_id,
                        batch_id,
                        study_id,
                        owner_id,
                        profile,
                        _json(options),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE dicom_studies SET status='queued',updated_at=? WHERE id=? AND owner_id=?",
                    (now, study_id, owner_id),
                )
                job_ids.append(job_id)
        jobs = [self.get_job(job_id, owner_id) for job_id in job_ids]
        return {"batch_id": batch_id, "status": "queued", "jobs": jobs, "job_count": len(jobs)}

    def _pixel_review_decisions(self, study_id: str, owner_id: str) -> dict[str, str]:
        """Translate completed API reviews into the core's per-SOP contract.

        A single accepted or unresolved pixel risk keeps the instance gated.
        The API never emits a global approval and never turns an accepted risk
        into ``verified_clear``.
        """
        placeholders = ",".join("?" for _ in _PIXEL_REVIEW_CODES)
        with self._connect() as conn:
            instances = conn.execute(
                "SELECT source_path,source_uid FROM dicom_instances WHERE study_id=? AND owner_id=?",
                (study_id, owner_id),
            ).fetchall()
            rows = conn.execute(
                f"SELECT code,status,source_path,source_sop_uid FROM dicom_risks "
                f"WHERE study_id=? AND owner_id=? AND code IN ({placeholders})",
                (study_id, owner_id, *_PIXEL_REVIEW_CODES),
            ).fetchall()
        decisions: dict[str, str] = {}
        for instance in instances:
            source_path = str(instance["source_path"])
            sop_uid = str(instance["source_uid"] or "")
            relevant = [
                row
                for row in rows
                if (row["source_path"] and str(row["source_path"]) == source_path)
                or (sop_uid and row["source_sop_uid"] and str(row["source_sop_uid"]) == sop_uid)
            ]
            if not relevant:
                continue
            if all(str(row["status"]) in {"resolved", "dismissed"} for row in relevant):
                decisions[sop_uid or source_path] = "verified_clear"
        return decisions

    def run_job(self, job_id: str, owner_id: str) -> None:
        with self._connect() as conn:
            job = conn.execute(
                "SELECT * FROM dicom_jobs WHERE id=? AND owner_id=?", (job_id, owner_id)
            ).fetchone()
            if not job or job["status"] != "queued":
                return
            now = _now()
            conn.execute(
                "UPDATE dicom_jobs SET status='running',progress=5,started_at=?,updated_at=? "
                "WHERE id=? AND owner_id=?",
                (now, now, job_id, owner_id),
            )
            conn.execute(
                "UPDATE dicom_studies SET status='running',updated_at=? WHERE id=? AND owner_id=?",
                (now, job["study_id"], owner_id),
            )
        try:
            paths = self.study_paths(job["study_id"], owner_id)
            output_dir = os.path.realpath(
                os.path.join(self.output_root, self.tenant_key(owner_id), job_id, "instances")
            )
            os.makedirs(output_dir, exist_ok=False)
            core_options = self._core_options(owner_id, _loads(job["options_json"], {}))
            core_options["pixel_review_decisions"] = self._pixel_review_decisions(
                job["study_id"], owner_id
            )
            result = self._core().anonymize_study(
                paths,
                output_dir=output_dir,
                profile=job["profile"],
                options=core_options,
            )
            if not isinstance(result, dict):
                raise ValueError("DICOM core returned a non-object result")
            if str(result.get("status") or "completed").lower() in {"failed", "error"}:
                raise ValueError(str(result.get("error") or "DICOM core reported failure"))

            requested_outputs = _as_list(result.get("output_paths"))
            output_paths: list[str] = []
            for value in requested_outputs:
                path = os.path.realpath(os.fspath(value))
                try:
                    inside = os.path.commonpath((path, output_dir)) == output_dir
                except ValueError:
                    inside = False
                if inside and os.path.isfile(path):
                    output_paths.append(path)
            if not output_paths:
                output_paths = [
                    os.path.realpath(os.path.join(root, name))
                    for root, _dirs, names in os.walk(output_dir)
                    for name in names
                    if os.path.isfile(os.path.join(root, name))
                ]
            if not output_paths:
                raise ValueError("DICOM core produced no output instances")

            zip_path = os.path.realpath(os.path.join(os.path.dirname(output_dir), f"{job_id}.zip"))
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for index, path in enumerate(sorted(set(output_paths))):
                    relative = os.path.relpath(path, output_dir).replace(os.sep, "/")
                    if relative.startswith("../") or relative == "..":
                        relative = f"instance-{index + 1}.dcm"
                    archive.write(path, relative)

            validation = _public_json(result.get("validation") or {})
            deidentification = result.get("report")
            if not isinstance(deidentification, dict):
                deidentification = {
                    key: value
                    for key, value in result.items()
                    if key not in {"output_paths", "validation"}
                }
            report = {
                "job_id": job_id,
                "study_id": job["study_id"],
                "profile": job["profile"],
                "options": _loads(job["options_json"], {}),
                "status": "completed",
                "output_instance_count": len(output_paths),
                "validation": validation,
                "deidentification": _public_json(deidentification),
                "completed_at": _now(),
            }
            validation_ok = (
                validation.get("passed", validation.get("ok"))
                if isinstance(validation, dict)
                else None
            )
            if validation_ok is False:
                raise DicomWorkflowError(
                    422,
                    "DICOM_OUTPUT_VALIDATION_FAILED",
                    "DICOM输出完整性验证失败",
                    {"validation": validation},
                )
            now = _now()
            with self._connect() as conn:
                conn.execute(
                    "UPDATE dicom_jobs SET status='completed',progress=100,completed_at=?,updated_at=?,"
                    "report_json=?,output_zip=?,error_code=NULL,error_message=NULL WHERE id=? AND owner_id=?",
                    (now, now, _json(report), zip_path, job_id, owner_id),
                )
                conn.execute(
                    "UPDATE dicom_studies SET status='completed',updated_at=? WHERE id=? AND owner_id=?",
                    (now, job["study_id"], owner_id),
                )
        except Exception as exc:
            logger.exception("DICOM anonymization job failed: job_id=%s", job_id)
            code = exc.error_code if isinstance(exc, DicomWorkflowError) else "DICOM_ANONYMIZATION_FAILED"
            message = (
                exc.message
                if isinstance(exc, DicomWorkflowError)
                else "DICOM匿名化执行失败，请查看服务端日志"
            )
            now = _now()
            with self._connect() as conn:
                conn.execute(
                    "UPDATE dicom_jobs SET status='failed',completed_at=?,updated_at=?,error_code=?,error_message=? "
                    "WHERE id=? AND owner_id=?",
                    (now, now, code, message, job_id, owner_id),
                )
                conn.execute(
                    "UPDATE dicom_studies SET status='failed',updated_at=? WHERE id=? AND owner_id=?",
                    (now, job["study_id"], owner_id),
                )

    @staticmethod
    def _public_job(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "job_id": row["id"],
            "batch_id": row["batch_id"],
            "study_id": row["study_id"],
            "profile": row["profile"],
            "status": row["status"],
            "progress": int(row["progress"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
            "error": row["error_message"] if row["error_code"] else None,
            "error_detail": (
                {"error_code": row["error_code"], "message": row["error_message"]}
                if row["error_code"]
                else None
            ),
        }

    def get_job(self, job_id: str, owner_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dicom_jobs WHERE id=? AND owner_id=?", (job_id, owner_id)
            ).fetchone()
        if not row:
            raise DicomWorkflowError(404, "DICOM_JOB_NOT_FOUND", "DICOM任务不存在")
        return self._public_job(row)

    def get_batch(self, batch_id: str, owner_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM dicom_jobs WHERE batch_id=? AND owner_id=? ORDER BY created_at,id",
                (batch_id, owner_id),
            ).fetchall()
        if not rows:
            raise DicomWorkflowError(404, "DICOM_BATCH_NOT_FOUND", "DICOM批量任务不存在")
        jobs = [self.get_job(row["id"], owner_id) for row in rows]
        statuses = {job["status"] for job in jobs}
        if statuses == {"completed"}:
            status = "completed"
        elif "failed" in statuses and statuses <= {"completed", "failed"}:
            status = "partial_failed" if "completed" in statuses else "failed"
        elif "running" in statuses:
            status = "running"
        else:
            status = "queued"
        return {
            "batch_id": batch_id,
            "status": status,
            "progress": int(sum(job["progress"] for job in jobs) / len(jobs)),
            "jobs": jobs,
        }

    def get_report(self, job_id: str, owner_id: str) -> dict[str, Any]:
        job = self.get_job(job_id, owner_id)
        if job["status"] == "failed":
            raise DicomWorkflowError(
                409,
                "DICOM_JOB_FAILED",
                "DICOM任务执行失败",
                job["error_detail"] or {},
            )
        if job["status"] != "completed":
            raise DicomWorkflowError(409, "DICOM_JOB_NOT_COMPLETE", "DICOM任务尚未完成")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT report_json FROM dicom_jobs WHERE id=? AND owner_id=?", (job_id, owner_id)
            ).fetchone()
        report = _loads(row["report_json"], {})
        risk_summary = self.risks(job["study_id"], owner_id)["summary"]
        report["risks_summary"] = risk_summary
        report["risk_summary"] = risk_summary
        deidentification = report.get("deidentification") if isinstance(report.get("deidentification"), dict) else {}
        validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
        with self._connect() as conn:
            source_count = conn.execute(
                "SELECT COUNT(*) FROM dicom_instances WHERE study_id=? AND owner_id=?",
                (job["study_id"], owner_id),
            ).fetchone()[0]
        identity_value = deidentification.get("patient_identity_removed")
        validation_passed = bool(validation.get("passed", validation.get("ok", False)))
        identity_removed = str(identity_value).upper() in {"YES", "TRUE", "1"}
        # The core validator explicitly rejects any instance whose
        # PatientIdentityRemoved flag is not YES.  This fallback also repairs
        # reports written by the immediately preceding DICOM build, before the
        # aggregate report carried the flag directly.
        if identity_value is None and validation_passed and int(source_count) > 0:
            identity_removed = True
        report.update(
            {
                "job_id": job_id,
                "study_id": job["study_id"],
                "source_instance_count": int(source_count),
                "patient_identity_removed": identity_removed,
                "deidentification_method": deidentification.get("deidentification_method") or report.get("profile"),
                "validation_status": "passed"
                if validation.get("passed", validation.get("ok", True))
                else "failed",
                "actions": deidentification.get("action_counts") or report.get("actions") or {},
            }
        )
        return _public_json(report)

    def export_path(self, job_id: str, owner_id: str) -> str:
        job = self.get_job(job_id, owner_id)
        if job["status"] != "completed":
            raise DicomWorkflowError(409, "DICOM_JOB_NOT_COMPLETE", "DICOM任务尚未完成")
        risks_summary = self.risks(job["study_id"], owner_id)["summary"]
        if risks_summary["blocking"]:
            raise DicomWorkflowError(
                409,
                "DICOM_REVIEW_REQUIRED",
                "仍有未解决的高风险项，禁止导出",
                {"blocking_risks": risks_summary["blocking"]},
            )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT output_zip FROM dicom_jobs WHERE id=? AND owner_id=?", (job_id, owner_id)
            ).fetchone()
        path = os.path.realpath(row["output_zip"] or "")
        if not path or not os.path.isfile(path):
            raise DicomWorkflowError(409, "DICOM_EXPORT_MISSING", "DICOM导出文件不可用")
        return path

    def batch_export_path(self, batch_id: str, owner_id: str) -> str:
        batch = self.get_batch(batch_id, owner_id)
        if batch["status"] != "completed":
            raise DicomWorkflowError(409, "DICOM_BATCH_NOT_COMPLETE", "DICOM批量任务尚未全部完成")
        paths = [(job, self.export_path(job["id"], owner_id)) for job in batch["jobs"]]
        batch_root = os.path.realpath(os.path.join(self.output_root, self.tenant_key(owner_id), "batches"))
        os.makedirs(batch_root, exist_ok=True)
        output = os.path.realpath(os.path.join(batch_root, f"{batch_id}.zip"))
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for job, path in paths:
                archive.write(path, f"{job['study_id']}/{job['id']}.zip")
        return output


@lru_cache(maxsize=1)
def get_dicom_job_service() -> DicomJobService:
    return DicomJobService()
