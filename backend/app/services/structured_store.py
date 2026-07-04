"""SQLite persistence for structured-table de-identification."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.sqlite_base import connect_sqlite, ensure_db_dir


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


_SCHEMA = """
CREATE TABLE IF NOT EXISTS structured_sources (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  file_path TEXT,
  status TEXT NOT NULL DEFAULT 'ready',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_sources_owner ON structured_sources(owner_id);

CREATE TABLE IF NOT EXISTS structured_connections (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  engine TEXT NOT NULL,
  display_name TEXT NOT NULL,
  credential_json TEXT NOT NULL,
  last_test_status TEXT,
  last_tested_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_connections_owner ON structured_connections(owner_id);

CREATE TABLE IF NOT EXISTS structured_datasets (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  source_id TEXT,
  connection_id TEXT,
  name TEXT NOT NULL,
  dataset_type TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  shape_kind TEXT NOT NULL DEFAULT 'flat_table',
  schema_name TEXT,
  table_name TEXT,
  row_count_estimate INTEGER,
  column_count INTEGER NOT NULL DEFAULT 0,
  schema_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_datasets_owner ON structured_datasets(owner_id);
CREATE INDEX IF NOT EXISTS idx_structured_datasets_source ON structured_datasets(source_id);
CREATE INDEX IF NOT EXISTS idx_structured_datasets_connection ON structured_datasets(connection_id);

CREATE TABLE IF NOT EXISTS structured_profiles (
  dataset_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_profiles_owner ON structured_profiles(owner_id);

CREATE TABLE IF NOT EXISTS structured_policies (
  dataset_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  policy_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_policies_owner ON structured_policies(owner_id);

CREATE TABLE IF NOT EXISTS structured_exports (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  dataset_id TEXT,
  export_format TEXT NOT NULL,
  file_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_structured_exports_owner_job ON structured_exports(owner_id, job_id);
"""


class StructuredStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout=10.0, busy_timeout_ms=5000, wal=True)

    def _init_db(self) -> None:
        ensure_db_dir(self.db_path)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def create_source(
        self,
        *,
        owner_id: str,
        source_type: str,
        kind: str,
        name: str,
        file_path: str | None = None,
        status: str = "ready",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_id = str(uuid.uuid4())
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_sources
                (id, owner_id, source_type, kind, name, file_path, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    owner_id,
                    source_type,
                    kind,
                    name,
                    file_path,
                    status,
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_source(source_id, owner_id=owner_id) or {}

    def list_sources(self, *, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM structured_sources WHERE owner_id = ? ORDER BY created_at DESC",
                (owner_id,),
            ).fetchall()
        return [self._source_out(dict(row)) for row in rows]

    def get_source(self, source_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM structured_sources WHERE id = ? AND owner_id = ?",
                (source_id, owner_id),
            ).fetchone()
        return self._source_out(dict(row)) if row else None

    @staticmethod
    def _source_out(row: dict[str, Any]) -> dict[str, Any]:
        row["metadata"] = _json_loads(row.pop("metadata_json", None), {})
        return row

    def create_connection(
        self,
        *,
        owner_id: str,
        engine: str,
        display_name: str,
        encrypted_credential: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        last_test_status: str | None = None,
    ) -> dict[str, Any]:
        connection_id = str(uuid.uuid4())
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_connections
                (id, owner_id, engine, display_name, credential_json, last_test_status, last_tested_at,
                 metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id,
                    owner_id,
                    engine,
                    display_name,
                    _json_dumps(encrypted_credential),
                    last_test_status,
                    now if last_test_status else None,
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_connection(connection_id, owner_id=owner_id, include_secret=True) or {}

    def list_connections(self, *, owner_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, owner_id, engine, display_name, last_test_status, last_tested_at,
                       metadata_json, created_at, updated_at
                FROM structured_connections
                WHERE owner_id = ?
                ORDER BY created_at DESC
                """,
                (owner_id,),
            ).fetchall()
        return [self._connection_out(dict(row)) for row in rows]

    def get_connection(
        self,
        connection_id: str,
        *,
        owner_id: str,
        include_secret: bool = False,
    ) -> dict[str, Any] | None:
        cols = "*" if include_secret else (
            "id, owner_id, engine, display_name, last_test_status, last_tested_at, "
            "metadata_json, created_at, updated_at"
        )
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {cols} FROM structured_connections WHERE id = ? AND owner_id = ?",
                (connection_id, owner_id),
            ).fetchone()
        if not row:
            return None
        raw = dict(row)
        credential = _json_loads(raw.get("credential_json"), {}) if include_secret else None
        out = self._connection_out(raw)
        if include_secret:
            out["credential"] = credential or {}
        return out

    def update_connection_test_status(
        self,
        connection_id: str,
        *,
        owner_id: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_iso()
        with self._connect() as conn:
            if metadata is None:
                conn.execute(
                    """
                    UPDATE structured_connections
                    SET last_test_status = ?, last_tested_at = ?, updated_at = ?
                    WHERE id = ? AND owner_id = ?
                    """,
                    (status, now, now, connection_id, owner_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE structured_connections
                    SET last_test_status = ?, last_tested_at = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ? AND owner_id = ?
                    """,
                    (status, now, _json_dumps(metadata), now, connection_id, owner_id),
                )
            conn.commit()

    def delete_connection(self, connection_id: str, *, owner_id: str) -> bool:
        with self._connect() as conn:
            dataset_rows = conn.execute(
                "SELECT id FROM structured_datasets WHERE connection_id = ? AND owner_id = ?",
                (connection_id, owner_id),
            ).fetchall()
            dataset_ids = [str(row["id"]) for row in dataset_rows]
            cur = conn.execute(
                "DELETE FROM structured_connections WHERE id = ? AND owner_id = ?",
                (connection_id, owner_id),
            )
            for dataset_id in dataset_ids:
                conn.execute(
                    "DELETE FROM structured_profiles WHERE dataset_id = ? AND owner_id = ?",
                    (dataset_id, owner_id),
                )
                conn.execute(
                    "DELETE FROM structured_policies WHERE dataset_id = ? AND owner_id = ?",
                    (dataset_id, owner_id),
                )
            conn.execute(
                "DELETE FROM structured_datasets WHERE connection_id = ? AND owner_id = ?",
                (connection_id, owner_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_dataset(self, dataset_id: str, *, owner_id: str) -> bool:
        """Remove one dataset with its profile/policy rows.

        The shared source file is kept on purpose: an xlsx upload spawns one
        dataset per sheet and siblings still reference the same source.
        """
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM structured_profiles WHERE dataset_id = ? AND owner_id = ?",
                (dataset_id, owner_id),
            )
            conn.execute(
                "DELETE FROM structured_policies WHERE dataset_id = ? AND owner_id = ?",
                (dataset_id, owner_id),
            )
            cur = conn.execute(
                "DELETE FROM structured_datasets WHERE id = ? AND owner_id = ?",
                (dataset_id, owner_id),
            )
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _connection_out(row: dict[str, Any]) -> dict[str, Any]:
        row["metadata"] = _json_loads(row.pop("metadata_json", None), {})
        row.pop("credential_json", None)
        return row

    def upsert_dataset(
        self,
        *,
        owner_id: str,
        name: str,
        dataset_type: str,
        source_kind: str,
        source_id: str | None = None,
        connection_id: str | None = None,
        shape_kind: str = "flat_table",
        schema_name: str | None = None,
        table_name: str | None = None,
        row_count_estimate: int | None = None,
        column_count: int = 0,
        schema: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_iso()
        did = dataset_id or str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_datasets
                (id, owner_id, source_id, connection_id, name, dataset_type, source_kind, shape_kind,
                 schema_name, table_name, row_count_estimate, column_count, schema_json, metadata_json,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  shape_kind = excluded.shape_kind,
                  row_count_estimate = excluded.row_count_estimate,
                  column_count = excluded.column_count,
                  schema_json = excluded.schema_json,
                  metadata_json = excluded.metadata_json,
                  updated_at = excluded.updated_at
                """,
                (
                    did,
                    owner_id,
                    source_id,
                    connection_id,
                    name,
                    dataset_type,
                    source_kind,
                    shape_kind,
                    schema_name,
                    table_name,
                    row_count_estimate,
                    int(column_count),
                    _json_dumps(schema or []),
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        dataset = self.get_dataset(did, owner_id=owner_id)
        if not dataset:
            raise RuntimeError("internal invariant: dataset is unexpectedly missing")
        return dataset

    def get_dataset(self, dataset_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  d.*,
                  p.updated_at AS profile_updated_at,
                  pol.updated_at AS policy_updated_at,
                  pol.policy_json AS policy_status_json
                FROM structured_datasets d
                LEFT JOIN structured_profiles p
                  ON p.dataset_id = d.id AND p.owner_id = d.owner_id
                LEFT JOIN structured_policies pol
                  ON pol.dataset_id = d.id AND pol.owner_id = d.owner_id
                WHERE d.id = ? AND d.owner_id = ?
                """,
                (dataset_id, owner_id),
            ).fetchone()
        return self._dataset_out(dict(row)) if row else None

    def list_datasets(
        self,
        *,
        owner_id: str,
        source_id: str | None = None,
        connection_id: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["d.owner_id = ?"]
        params: list[Any] = [owner_id]
        if source_id:
            where.append("d.source_id = ?")
            params.append(source_id)
        if connection_id:
            where.append("d.connection_id = ?")
            params.append(connection_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  d.*,
                  p.updated_at AS profile_updated_at,
                  pol.updated_at AS policy_updated_at,
                  pol.policy_json AS policy_status_json
                FROM structured_datasets d
                LEFT JOIN structured_profiles p
                  ON p.dataset_id = d.id AND p.owner_id = d.owner_id
                LEFT JOIN structured_policies pol
                  ON pol.dataset_id = d.id AND pol.owner_id = d.owner_id
                WHERE {' AND '.join(where)}
                ORDER BY d.created_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [self._dataset_out(dict(row)) for row in rows]

    @staticmethod
    def _dataset_out(row: dict[str, Any]) -> dict[str, Any]:
        row["schema"] = _json_loads(row.pop("schema_json", None), [])
        row["metadata"] = _json_loads(row.pop("metadata_json", None), {})
        policy_status = _json_loads(row.pop("policy_status_json", None), {})
        row["policy_reviewed_at"] = (
            policy_status.get("reviewed_at") if isinstance(policy_status, dict) else None
        )
        return row

    def save_profile(self, dataset_id: str, *, owner_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_profiles (dataset_id, owner_id, profile_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                  profile_json = excluded.profile_json,
                  updated_at = excluded.updated_at
                """,
                (dataset_id, owner_id, _json_dumps(profile), now),
            )
            conn.commit()
        profile["updated_at"] = now
        return profile

    def get_profile(self, dataset_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM structured_profiles WHERE dataset_id = ? AND owner_id = ?",
                (dataset_id, owner_id),
            ).fetchone()
        if not row:
            return None
        data = _json_loads(row["profile_json"], {})
        if isinstance(data, dict):
            data["updated_at"] = row["updated_at"]
            return data
        return None

    def save_policy(self, dataset_id: str, *, owner_id: str, policy: dict[str, Any]) -> dict[str, Any]:
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_policies (dataset_id, owner_id, policy_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                  policy_json = excluded.policy_json,
                  updated_at = excluded.updated_at
                """,
                (dataset_id, owner_id, _json_dumps(policy), now),
            )
            conn.commit()
        policy["updated_at"] = now
        return policy

    def get_policy(self, dataset_id: str, *, owner_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM structured_policies WHERE dataset_id = ? AND owner_id = ?",
                (dataset_id, owner_id),
            ).fetchone()
        if not row:
            return None
        data = _json_loads(row["policy_json"], {})
        if isinstance(data, dict):
            data["updated_at"] = row["updated_at"]
            return data
        return None

    def add_export(
        self,
        *,
        owner_id: str,
        job_id: str,
        dataset_id: str | None,
        export_format: str,
        file_path: str,
        filename: str,
        summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        export_id = str(uuid.uuid4())
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO structured_exports
                (id, owner_id, job_id, dataset_id, export_format, file_path, filename, summary_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    export_id,
                    owner_id,
                    job_id,
                    dataset_id,
                    export_format,
                    file_path,
                    filename,
                    _json_dumps(summary or {}),
                    now,
                ),
            )
            conn.commit()
        return {
            "id": export_id,
            "owner_id": owner_id,
            "job_id": job_id,
            "dataset_id": dataset_id,
            "export_format": export_format,
            "file_path": file_path,
            "filename": filename,
            "summary": summary or {},
            "created_at": now,
        }

    def list_exports(self, *, owner_id: str, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM structured_exports
                WHERE owner_id = ? AND job_id = ?
                ORDER BY created_at ASC
                """,
                (owner_id, job_id),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["summary"] = _json_loads(item.pop("summary_json", None), {})
            out.append(item)
        return out


@lru_cache
def get_structured_store() -> StructuredStore:
    db_path = os.path.join(settings.DATA_DIR, "structured_store.sqlite3")
    return StructuredStore(db_path)
