from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import structured_service
from app.services.structured_store import StructuredStore


def _payload_from_url(url: str, *, engine: str) -> dict[str, object]:
    sa = structured_service.sqlalchemy()
    parsed = sa.engine.make_url(url)
    return {
        "engine": engine,
        "display_name": f"{engine} integration database",
        "host": parsed.host or "127.0.0.1",
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username or "",
        "password": parsed.password or "",
    }


def _create_demo_table(url: str, table_name: str, *, engine: str) -> None:
    sa = structured_service.sqlalchemy()
    sql_engine = sa.create_engine(url)
    ident = sql_engine.dialect.identifier_preparer.quote(table_name)
    int_type = "INTEGER" if engine == "postgres" else "INT"
    try:
        with sql_engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {ident}"))
            conn.execute(
                sa.text(
                    f"""
                    CREATE TABLE {ident} (
                        id {int_type} PRIMARY KEY,
                        customer_name VARCHAR(128),
                        mobile_phone VARCHAR(32),
                        email VARCHAR(128),
                        id_card VARCHAR(32),
                        shipping_address VARCHAR(255),
                        billing_amount DECIMAL(12, 2),
                        order_note VARCHAR(255)
                    )
                    """
                )
            )
            conn.execute(
                sa.text(
                    f"""
                    INSERT INTO {ident}
                    (id, customer_name, mobile_phone, email, id_card, shipping_address, billing_amount, order_note)
                    VALUES
                    (1, 'Alice Zhang', '13800138000', 'alice@example.com', '11010119900307421X',
                     'Shanghai Pudong Century Avenue 100', 1294000.00, 'priority customer'),
                    (2, 'Bob Li', '13900139000', 'bob@example.com', '110101198812123456',
                     'Beijing Haidian Zhongguancun Street 1', 86000.00, 'standard delivery')
                    """
                )
            )
    finally:
        sql_engine.dispose()


def _drop_demo_table(url: str, table_name: str) -> None:
    sa = structured_service.sqlalchemy()
    sql_engine = sa.create_engine(url)
    ident = sql_engine.dialect.identifier_preparer.quote(table_name)
    try:
        with sql_engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {ident}"))
    finally:
        sql_engine.dispose()


def _assert_real_database_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, engine: str, url: str) -> None:
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")

    table_name = f"structured_pii_{uuid4().hex[:10]}"
    _create_demo_table(url, table_name, engine=engine)
    try:
        store = StructuredStore(str(tmp_path / f"{engine}_structured.sqlite3"))
        payload = _payload_from_url(url, engine=engine)
        connection = structured_service.create_connection(
            owner_id="tenant_real_db",
            payload=payload,
            store=store,
        )

        discovered = structured_service.discover_connection_datasets(
            connection["id"],
            owner_id="tenant_real_db",
            store=store,
        )
        target = next(item for item in discovered if item["table_name"] == table_name)
        assert target["source_kind"] == engine
        assert target["connection_id"] == connection["id"]
        assert target["column_count"] == 8

        registered = structured_service.register_connection_datasets(
            connection["id"],
            owner_id="tenant_real_db",
            selections=[
                {
                    "schema_name": target.get("schema_name"),
                    "table_name": target["table_name"],
                }
            ],
            store=store,
        )
        assert len(registered) == 1
        dataset_id = registered[0]["id"]

        profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_real_db", store=store)
        by_name = {col["name"]: col for col in profile["columns"]}
        assert by_name["customer_name"]["entity_type"] == "PERSON"
        assert by_name["mobile_phone"]["entity_type"] == "PHONE"
        assert by_name["email"]["entity_type"] == "EMAIL"
        assert by_name["id_card"]["entity_type"] == "ID_CARD"
        assert by_name["shipping_address"]["entity_type"] == "ADDRESS"
        assert by_name["billing_amount"]["recommended_policy"] == "keep"
        assert by_name["order_note"]["recommended_policy"] == "keep"

        preview = structured_service.preview_dataset(dataset_id, owner_id="tenant_real_db", store=store)
        original = preview["original_rows"][0]
        redacted = preview["redacted_rows"][0]
        for column in ["customer_name", "mobile_phone", "email", "id_card", "shipping_address"]:
            assert redacted[column] != original[column]
        assert redacted["billing_amount"] == original["billing_amount"]
        assert redacted["order_note"] == original["order_note"]

        export = structured_service.export_dataset(
            dataset_id,
            owner_id="tenant_real_db",
            job_id=f"{engine}_integration_job",
            export_format="csv",
            store=store,
        )
        content = Path(export["file_path"]).read_text(encoding="utf-8-sig")
        assert "13800138000" not in content
        assert "alice@example.com" not in content
        assert "11010119900307421X" not in content
        assert "priority customer" in content
    finally:
        _drop_demo_table(url, table_name)


@pytest.mark.skipif(
    not os.environ.get("STRUCTURED_TEST_MYSQL_URL"),
    reason="Set STRUCTURED_TEST_MYSQL_URL to run the real MySQL structured-data integration test.",
)
def test_structured_mysql_real_database_flow(tmp_path, monkeypatch):
    _assert_real_database_flow(
        tmp_path,
        monkeypatch,
        engine="mysql",
        url=os.environ["STRUCTURED_TEST_MYSQL_URL"],
    )


@pytest.mark.skipif(
    not os.environ.get("STRUCTURED_TEST_POSTGRES_URL"),
    reason="Set STRUCTURED_TEST_POSTGRES_URL to run the real PostgreSQL structured-data integration test.",
)
def test_structured_postgres_real_database_flow(tmp_path, monkeypatch):
    _assert_real_database_flow(
        tmp_path,
        monkeypatch,
        engine="postgres",
        url=os.environ["STRUCTURED_TEST_POSTGRES_URL"],
    )
