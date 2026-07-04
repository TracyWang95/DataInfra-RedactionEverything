"""Database connection handling: credentials, SQLAlchemy access, connection dataset discovery."""
from __future__ import annotations

import ipaddress
import json
import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from app.core.config import settings
from app.services.structured_common import LoadedTable, utc_iso
from app.services.structured_files import discover_sqlite_datasets, read_sqlite_table
from app.services.structured_store import StructuredStore, get_structured_store

_DEFAULT_DATASET_DISCOVERY_LIMIT = 500


def credential_key_path() -> str:
    return os.path.join(settings.DATA_DIR, "structured_credentials.key")


def _fernet() -> Fernet:
    path = credential_key_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(Fernet.generate_key())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path, "rb") as fh:
        return Fernet(fh.read().strip())


def encrypt_credential(payload: dict[str, Any]) -> dict[str, str]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"encrypted": _fernet().encrypt(raw).decode("ascii")}


def decrypt_credential(payload: dict[str, Any]) -> dict[str, Any]:
    token = payload.get("encrypted") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        return {}
    raw = _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def annotate_discovered_connection_datasets(
    datasets: Iterable[dict[str, Any]],
    *,
    connection_id: str,
) -> list[dict[str, Any]]:
    now = utc_iso()
    annotated: list[dict[str, Any]] = []
    for dataset in datasets:
        item = dict(dataset)
        item["source_id"] = item.get("source_id") or None
        item["connection_id"] = connection_id
        item.setdefault("created_at", now)
        item.setdefault("id", stable_discovered_dataset_id(connection_id, item))
        annotated.append(item)
    return annotated


def stable_discovered_dataset_id(connection_id: str, dataset: dict[str, Any]) -> str:
    schema = str(dataset.get("schema_name") or "")
    table = str(dataset.get("table_name") or dataset.get("name") or "")
    dataset_type = str(dataset.get("dataset_type") or "")
    key = f"structured-discovery:{connection_id}:{schema}:{table}:{dataset_type}"
    return f"discovered:{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}"


def read_connection_table(
    connection: dict[str, Any],
    credential: dict[str, Any],
    *,
    schema_name: str | None,
    table_name: str,
    limit: int | None,
) -> LoadedTable:
    engine = str(connection.get("engine") or "")
    if engine == "sqlite":
        path = str(credential.get("sqlite_path") or credential.get("database") or "")
        return read_sqlite_table(path, table_name=table_name, limit=limit)
    sa = sqlalchemy()
    url = build_sqlalchemy_url({**credential, "engine": engine})
    sql_engine = sa.create_engine(url)
    try:
        table_ref = quote_sa_table(sa, sql_engine, schema_name=schema_name, table_name=table_name)
        with sql_engine.connect() as conn:
            empty_result = conn.execute(sa.text(f"SELECT * FROM {table_ref} LIMIT 0"))
            columns = [str(key) for key in empty_result.keys()]
            total = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table_ref}")).scalar_one_or_none()
            sql = f"SELECT * FROM {table_ref}"
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            rows = [dict(row._mapping) for row in conn.execute(sa.text(sql)).fetchall()]
        return LoadedTable(columns=columns, rows=rows, row_count_estimate=int(total or 0))
    finally:
        sql_engine.dispose()


def sqlalchemy():
    import sqlalchemy as sa

    return sa


def quote_sa_table(sa: Any, engine: Any, *, schema_name: str | None, table_name: str) -> str:
    preparer = engine.dialect.identifier_preparer
    table = preparer.quote(table_name)
    if schema_name:
        return f"{preparer.quote(schema_name)}.{table}"
    del sa
    return table


def _validate_db_host_allowed(host: str) -> None:
    """SSRF guard: when STRUCTURED_DB_HOST_ALLOWLIST is set, reject hosts outside it.

    Allowlist entries are exact hostnames or IP / CIDR networks. ``None`` means
    no restriction (default), preserving the local-tool use case of connecting
    to the user's own databases.
    """
    allowlist = settings.STRUCTURED_DB_HOST_ALLOWLIST
    if allowlist is None:
        return
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    for raw_entry in allowlist:
        entry = str(raw_entry).strip()
        if not entry:
            continue
        if host == entry:
            return
        if addr is not None:
            try:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return
            except ValueError:
                continue
    raise ValueError(
        f"database host '{host}' is blocked by STRUCTURED_DB_HOST_ALLOWLIST; "
        "add the exact hostname or an IP/CIDR entry to the allowlist to permit this connection"
    )


def build_sqlalchemy_url(payload: dict[str, Any]) -> str:
    engine = str(payload.get("engine") or "")
    if engine == "mysql":
        driver = "mysql+pymysql"
        port = int(payload.get("port") or 3306)
    elif engine == "postgres":
        driver = "postgresql+psycopg"
        port = int(payload.get("port") or 5432)
    elif engine == "sqlite":
        path = str(payload.get("sqlite_path") or payload.get("database") or "")
        return f"sqlite:///{Path(path).as_posix()}"
    else:
        raise ValueError(f"unsupported database engine: {engine}")
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    host = str(payload.get("host") or "localhost")
    _validate_db_host_allowed(host)
    database = str(payload.get("database") or "")
    from urllib.parse import quote_plus

    return f"{driver}://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"


def test_connection(payload: dict[str, Any]) -> dict[str, Any]:
    datasets = discover_connection_datasets_from_payload(payload, limit=50)
    return {
        "ok": True,
        "message": "connection ok",
        "engine": payload.get("engine"),
        "dataset_count": len(datasets),
    }


def connection_display_metadata(payload: dict[str, Any], *, dataset_count: int) -> dict[str, Any]:
    """Return non-secret connection details that help users identify saved targets."""
    engine = str(payload.get("engine") or "")
    metadata: dict[str, Any] = {
        "dataset_count": int(dataset_count),
    }
    if engine == "sqlite":
        sqlite_path = str(payload.get("sqlite_path") or payload.get("database") or "").strip()
        if sqlite_path:
            metadata["sqlite_path"] = sqlite_path
            metadata["target"] = sqlite_path
        return metadata

    host = str(payload.get("host") or "").strip()
    port = payload.get("port")
    database = str(payload.get("database") or "").strip()
    username = str(payload.get("username") or "").strip()
    if host:
        metadata["host"] = host
    if port:
        metadata["port"] = int(port)
    if database:
        metadata["database"] = database
    if username:
        metadata["username"] = username
    endpoint = host
    if port:
        endpoint = f"{endpoint}:{int(port)}" if endpoint else str(int(port))
    if database:
        endpoint = f"{endpoint}/{database}" if endpoint else database
    if endpoint:
        metadata["target"] = endpoint
    return metadata


def create_connection(
    *,
    owner_id: str,
    payload: dict[str, Any],
    store: StructuredStore | None = None,
) -> dict[str, Any]:
    store = store or get_structured_store()
    test = test_connection(payload)
    connection = store.create_connection(
        owner_id=owner_id,
        engine=str(payload.get("engine")),
        display_name=str(payload.get("display_name") or payload.get("database") or payload.get("sqlite_path") or "Database"),
        encrypted_credential=encrypt_credential(payload),
        last_test_status="ok" if test["ok"] else "failed",
        metadata=connection_display_metadata(payload, dataset_count=int(test["dataset_count"])),
    )
    return connection


def discover_connection_datasets(
    connection_id: str,
    *,
    owner_id: str,
    store: StructuredStore | None = None,
) -> list[dict[str, Any]]:
    store = store or get_structured_store()
    connection = store.get_connection(connection_id, owner_id=owner_id, include_secret=True)
    if not connection:
        raise ValueError("connection not found")
    credential = decrypt_credential(connection.get("credential") or {})
    datasets = discover_connection_datasets_from_payload({**credential, "engine": connection["engine"]})
    return annotate_discovered_connection_datasets(datasets, connection_id=connection_id)


def register_connection_datasets(
    connection_id: str,
    *,
    owner_id: str,
    selections: list[dict[str, Any]],
    store: StructuredStore | None = None,
) -> list[dict[str, Any]]:
    store = store or get_structured_store()
    connection = store.get_connection(connection_id, owner_id=owner_id, include_secret=True)
    if not connection:
        raise ValueError("connection not found")
    discovered = discover_connection_datasets(connection_id, owner_id=owner_id, store=store)
    by_key = {
        (item.get("schema_name"), item.get("table_name") or item.get("name")): item for item in discovered
    }
    selected: list[dict[str, Any]] = []
    for raw in selections:
        key = (raw.get("schema_name"), raw.get("table_name") or raw.get("name"))
        item = by_key.get(key)
        if not item:
            continue
        selected.append(
            store.upsert_dataset(
                owner_id=owner_id,
                connection_id=connection_id,
                source_id=None,
                name=item["name"],
                dataset_type=item["dataset_type"],
                source_kind=str(connection["engine"]),
                shape_kind=item.get("shape_kind") or "flat_table",
                schema_name=item.get("schema_name"),
                table_name=item.get("table_name"),
                row_count_estimate=item.get("row_count_estimate"),
                column_count=int(item.get("column_count") or 0),
                schema=item.get("schema") or [],
                metadata=item.get("metadata") or {},
            )
        )
    return selected


def discover_connection_datasets_from_payload(payload: dict[str, Any], *, limit: int = _DEFAULT_DATASET_DISCOVERY_LIMIT) -> list[dict[str, Any]]:
    engine = str(payload.get("engine") or "")
    if engine == "sqlite":
        path = str(payload.get("sqlite_path") or payload.get("database") or "")
        if not path or not os.path.exists(path):
            raise ValueError("sqlite database path not found")
        return discover_sqlite_datasets(path, source_id=None, source_kind="sqlite")[:limit]
    sa = sqlalchemy()
    sql_engine = sa.create_engine(build_sqlalchemy_url(payload))
    datasets: list[dict[str, Any]] = []
    try:
        inspector = sa.inspect(sql_engine)
        for schema_name in inspector.get_schema_names():
            if schema_name in {"information_schema", "pg_catalog", "mysql", "performance_schema", "sys"}:
                continue
            table_names = inspector.get_table_names(schema=schema_name)
            view_names = inspector.get_view_names(schema=schema_name)
            for table_name, dataset_type in [(name, "db_table") for name in table_names] + [
                (name, "db_view") for name in view_names
            ]:
                columns = inspector.get_columns(table_name, schema=schema_name)
                schema = [{"name": col["name"], "data_type": str(col.get("type") or "string")} for col in columns]
                datasets.append(
                    {
                        "source_id": None,
                        "connection_id": None,
                        "name": f"{schema_name}.{table_name}" if schema_name else table_name,
                        "dataset_type": dataset_type,
                        "source_kind": engine,
                        "shape_kind": "flat_table",
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "row_count_estimate": None,
                        "column_count": len(schema),
                        "schema": schema,
                        "metadata": {},
                    }
                )
                if len(datasets) >= limit:
                    return datasets
    finally:
        sql_engine.dispose()
    return datasets


def _iter_connection_rows(connection, credential, *, schema_name, table_name):
    sa = sqlalchemy()
    engine = str(connection.get("engine") or "")
    url = build_sqlalchemy_url({**credential, "engine": engine})
    sql_engine = sa.create_engine(url)
    try:
        table_ref = quote_sa_table(sa, sql_engine, schema_name=schema_name, table_name=table_name)
        with sql_engine.connect() as conn:
            columns = [str(key) for key in conn.execute(sa.text(f"SELECT * FROM {table_ref} LIMIT 0")).keys()]
    except Exception:
        sql_engine.dispose()
        raise

    def rows():
        try:
            with sql_engine.connect() as conn:
                result = conn.execution_options(stream_results=True, yield_per=1000).execute(
                    sa.text(f"SELECT * FROM {table_ref}")
                )
                for row in result:
                    yield dict(row._mapping)
        finally:
            sql_engine.dispose()

    return columns, rows()
