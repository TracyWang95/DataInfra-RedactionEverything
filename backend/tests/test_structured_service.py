from __future__ import annotations

import csv
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.services.job_management_service as job_service
import app.services.structured_store as structured_store_module
from app.api import structured as structured_api
from app.core.auth import require_auth
from app.services import structured_service
from app.services.job_store import JobStore, JobType, get_job_store
from app.services.structured_store import StructuredStore, get_structured_store


def _write_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["姓名", "手机号", "邮箱", "合计金额"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "姓名": "张三",
                "手机号": "13800138000",
                "邮箱": "zhangsan@example.com",
                "合计金额": "1294000",
            }
        )


def _write_demo_customer_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "customer_name",
                "mobile_phone",
                "email",
                "id_card",
                "billing_amount",
                "shipping_address",
                "order_note",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "customer_name": "Alice Zhang",
                "mobile_phone": "13800138000",
                "email": "alice@example.com",
                "id_card": "11010119900307421X",
                "billing_amount": "1294000",
                "shipping_address": "Shanghai Pudong Century Avenue 100",
                "order_note": "priority customer",
            }
        )
        writer.writerow(
            {
                "customer_name": "Bob Li",
                "mobile_phone": "13900139000",
                "email": "bob@example.com",
                "id_card": "110101198812123456",
                "billing_amount": "86000",
                "shipping_address": "Beijing Haidian Zhongguancun Street 1",
                "order_note": "standard delivery",
            }
        )


def _write_demo_customer_sqlite(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE customers (
                opaque_name TEXT,
                contact TEXT,
                email TEXT,
                id_no TEXT,
                ship_to TEXT,
                amount INTEGER,
                memo TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO customers
            (opaque_name, contact, email, id_no, ship_to, amount, memo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "Alice Zhang",
                    "13800138000",
                    "alice@example.com",
                    "11010119900307421X",
                    "Shanghai Pudong Century Avenue 100",
                    1294000,
                    "priority customer",
                ),
                (
                    "Bob Li",
                    "13900139000",
                    "bob@example.com",
                    "110101198812123456",
                    "Beijing Haidian Zhongguancun Street 1",
                    86000,
                    "standard delivery",
                ),
            ],
        )


def test_demo_customer_table_runs_full_structured_redaction_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "demo_customers.csv"
    _write_demo_customer_csv(csv_path)

    result = structured_service.register_file_source(
        owner_id="admin",
        filename="demo_customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]

    profile = structured_service.profile_dataset(dataset_id, owner_id="admin", store=store)
    by_name = {col["name"]: col for col in profile["columns"]}
    assert by_name["customer_name"]["entity_type"] == "PERSON"
    assert by_name["mobile_phone"]["entity_type"] == "PHONE"
    assert by_name["email"]["entity_type"] == "EMAIL"
    assert by_name["id_card"]["entity_type"] == "ID_CARD"
    assert by_name["billing_amount"]["entity_type"] == "AMOUNT"
    assert by_name["billing_amount"]["recommended_policy"] == "keep"
    assert by_name["shipping_address"]["entity_type"] == "ADDRESS"
    assert by_name["order_note"]["recommended_policy"] == "keep"

    preview = structured_service.preview_dataset(dataset_id, owner_id="admin", store=store)
    original = preview["original_rows"][0]
    redacted = preview["redacted_rows"][0]
    for column in ["customer_name", "mobile_phone", "email", "id_card", "shipping_address"]:
        assert redacted[column] != original[column]
    assert redacted["billing_amount"] == original["billing_amount"]
    assert redacted["order_note"] == original["order_note"]

    export = structured_service.export_dataset(
        dataset_id,
        owner_id="admin",
        job_id="demo_structured_job",
        export_format="csv",
        store=store,
    )
    assert export["filename"] == "demo_customers.csv"
    assert Path(export["file_path"]).name == "demo_customers.csv"
    content = Path(export["file_path"]).read_text(encoding="utf-8-sig")
    sensitive_columns = [
        name
        for name, col in by_name.items()
        if col["recommended_policy"] != "keep"
    ]
    for row in preview["original_rows"]:
        for column in sensitive_columns:
            assert str(row[column]) not in content
    assert "priority customer" in content

    zip_path = structured_service.build_job_export_zip(owner_id="admin", job_id="demo_structured_job", store=store)
    with zipfile.ZipFile(zip_path) as zf:
        assert "demo_customers.csv" in zf.namelist()
        manifest = json.loads(zf.read("quality-report.json"))
    assert manifest["exports"][0]["filename"] == "demo_customers.csv"


def test_business_descriptor_name_columns_are_not_treated_as_person_pii(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: False)

    csv_path = tmp_path / "enterprise_orders.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "product_name",
                "device_name",
                "model_name",
                "receiver_name",
                "account_name",
                "contact_phone",
                "company_name",
                "商品名称",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "product_name": "GPU服务器",
                "device_name": "AI训练节点",
                "model_name": "NF5488M6",
                "receiver_name": "张三",
                "account_name": "李四",
                "contact_phone": "13800138000",
                "company_name": "北京智算科技有限公司",
                "商品名称": "高速交换机",
            }
        )

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="enterprise_orders.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )

    profile = structured_service.profile_dataset(result["datasets"][0]["id"], owner_id="tenant_a", store=store)
    by_name = {col["name"]: col for col in profile["columns"]}
    for column in ["product_name", "device_name", "model_name", "商品名称"]:
        assert by_name[column]["entity_type"] == "CUSTOM"
        assert by_name[column]["recommended_policy"] == "keep"
        assert "business_descriptor" in by_name[column]["reasons"]
    assert by_name["company_name"]["entity_type"] == "ORG"
    assert by_name["company_name"]["recommended_policy"] == "keep"
    assert by_name["receiver_name"]["entity_type"] == "PERSON"
    assert by_name["receiver_name"]["recommended_policy"] != "keep"
    assert by_name["account_name"]["entity_type"] == "PERSON"
    assert by_name["account_name"]["recommended_policy"] != "keep"
    assert by_name["contact_phone"]["entity_type"] == "PHONE"
    assert by_name["contact_phone"]["recommended_policy"] != "keep"


def test_deterministic_structured_columns_skip_has_semantic_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: True)

    class UnexpectedHaSClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HaS should not be called for deterministic structured columns")

    monkeypatch.setattr("app.services.has_client.HaSClient", UnexpectedHaSClient)

    csv_path = tmp_path / "deterministic_columns.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["customer_id", "customer_name", "mobile_phone", "email", "product_name", "tier"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "customer_id": "C001",
                "customer_name": "张三",
                "mobile_phone": "13800138000",
                "email": "zhangsan@example.com",
                "product_name": "GPU服务器",
                "tier": "gold",
            }
        )

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="deterministic_columns.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    profile = structured_service.profile_dataset(result["datasets"][0]["id"], owner_id="tenant_a", store=store)

    assert profile["semantic_inference"]["status"] == "skipped_no_candidates"
    by_name = {col["name"]: col for col in profile["columns"]}
    assert by_name["customer_name"]["entity_type"] == "PERSON"
    assert by_name["mobile_phone"]["entity_type"] == "PHONE"
    assert by_name["product_name"]["recommended_policy"] == "keep"


def test_has_semantic_inference_lifts_ambiguous_column_to_pii(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: True)

    class FakeHaSClient:
        def __init__(self, *args, **kwargs):
            pass

        def ner(self, text, entity_types):
            assert "col_a" in text
            return {"姓名": ["张三", "李四"]}

    monkeypatch.setattr("app.services.has_client.HaSClient", FakeHaSClient)

    csv_path = tmp_path / "ambiguous.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["col_a", "note"])
        writer.writeheader()
        writer.writerow({"col_a": "张三", "note": "normal"})
        writer.writerow({"col_a": "李四", "note": "normal"})

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="ambiguous.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
    by_name = {col["name"]: col for col in profile["columns"]}
    assert profile["semantic_inference"]["status"] == "used"
    assert profile["semantic_inference"]["matched_columns"] == 1
    assert by_name["col_a"]["entity_type"] == "PERSON"
    assert "semantic_model" in by_name["col_a"]["reasons"]
    assert by_name["note"]["recommended_policy"] == "keep"

    preview = structured_service.preview_dataset(dataset_id, owner_id="tenant_a", store=store)
    assert preview["redacted_rows"][0]["col_a"] != "张三"
    assert preview["redacted_rows"][0]["note"] == "normal"


def test_structured_has_semantic_inference_uses_short_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service.settings, "HAS_TIMEOUT", 120.0)
    monkeypatch.setattr(structured_service.settings, "STRUCTURED_HAS_TIMEOUT", 3.5)
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: True)

    seen_timeouts: list[float] = []
    seen_retries: list[int] = []

    class FakeHaSClient:
        def __init__(self, *args, **kwargs):
            seen_timeouts.append(kwargs["timeout"])
            seen_retries.append(kwargs["max_retries"])

        def ner(self, text, entity_types):
            assert "col_a" in text
            return {"姓名": ["张三"]}

    monkeypatch.setattr("app.services.has_client.HaSClient", FakeHaSClient)

    csv_path = tmp_path / "short_timeout.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["col_a", "note"])
        writer.writeheader()
        writer.writerow({"col_a": "张三", "note": "normal"})

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="short_timeout.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    structured_service.profile_dataset(result["datasets"][0]["id"], owner_id="tenant_a", store=store)

    assert seen_timeouts == [3.5]
    assert seen_retries == [0]


def test_short_integer_row_id_stays_technical_identifier(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: True)

    class FakeHaSClient:
        def __init__(self, *args, **kwargs):
            pass

        def ner(self, text, entity_types):
            assert "id_card" in text
            assert 'Column "id"' not in text
            return {"\u7535\u8bdd": ["1", "2"]}

    monkeypatch.setattr("app.services.has_client.HaSClient", FakeHaSClient)

    csv_path = tmp_path / "technical_id_customers.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "customer_name", "id_card", "mobile_phone"])
        writer.writeheader()
        writer.writerow(
            {
                "id": "1",
                "customer_name": "Alice Zhang",
                "id_card": "11010119900307421X",
                "mobile_phone": "13800138000",
            }
        )
        writer.writerow(
            {
                "id": "2",
                "customer_name": "Bob Li",
                "id_card": "110101198812123456",
                "mobile_phone": "13900139000",
            }
        )

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="technical_id_customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )

    profile = structured_service.profile_dataset(result["datasets"][0]["id"], owner_id="tenant_a", store=store)
    by_name = {col["name"]: col for col in profile["columns"]}
    assert by_name["id"]["entity_type"] == "CUSTOM"
    assert by_name["id"]["recommended_policy"] == "keep"
    assert by_name["id"]["reasons"] == ["technical_identifier"]
    assert by_name["id_card"]["entity_type"] == "ID_CARD"
    assert by_name["mobile_phone"]["entity_type"] == "PHONE"


def test_csv_profile_preview_and_export(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_csv(csv_path)

    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]

    profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
    by_name = {col["name"]: col for col in profile["columns"]}
    assert by_name["手机号"]["entity_type"] == "PHONE"
    assert by_name["邮箱"]["entity_type"] == "EMAIL"
    assert by_name["合计金额"]["entity_type"] == "AMOUNT"
    assert by_name["合计金额"]["recommended_policy"] == "keep"

    preview = structured_service.preview_dataset(dataset_id, owner_id="tenant_a", store=store)
    assert preview["original_rows"][0]["手机号"] == "13800138000"
    assert preview["redacted_rows"][0]["手机号"] != "13800138000"
    assert preview["redacted_rows"][0]["邮箱"] != "zhangsan@example.com"
    assert preview["redacted_rows"][0]["合计金额"] == "1294000"

    export = structured_service.export_dataset(
        dataset_id,
        owner_id="tenant_a",
        job_id="job_structured",
        export_format="csv",
        store=store,
    )
    assert Path(export["file_path"]).exists()
    content = Path(export["file_path"]).read_text(encoding="utf-8-sig")
    assert "13800138000" not in content
    assert "zhangsan@example.com" not in content
    assert "1294000" in content


def test_same_named_datasets_export_with_unique_delivery_filenames(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: False)

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    dataset_ids: list[str] = []
    markers = ["FIRST_SOURCE_MARKER", "SECOND_SOURCE_MARKER"]

    for index, marker in enumerate(markers, start=1):
        csv_path = tmp_path / f"source_{index}" / "customers.csv"
        csv_path.parent.mkdir()
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["customer_name", "mobile_phone", "public_note"])
            writer.writeheader()
            writer.writerow(
                {
                    "customer_name": f"Customer {index}",
                    "mobile_phone": f"1380013800{index}",
                    "public_note": marker,
                }
            )
        result = structured_service.register_file_source(
            owner_id="tenant_a",
            filename="customers.csv",
            file_path=str(csv_path),
            kind="csv",
            store=store,
        )
        dataset_ids.append(result["datasets"][0]["id"])

    exports = [
        structured_service.export_dataset(
            dataset_id,
            owner_id="tenant_a",
            job_id="same_name_job",
            export_format="csv",
            store=store,
        )
        for dataset_id in dataset_ids
    ]
    filenames = [export["filename"] for export in exports]
    assert filenames[0] == "customers.csv"
    assert filenames[1].startswith("customers-2-")
    assert filenames[1].endswith(".csv")
    assert len(set(filenames)) == 2
    assert len({Path(export["file_path"]) for export in exports}) == 2

    first_content = Path(exports[0]["file_path"]).read_text(encoding="utf-8-sig")
    second_content = Path(exports[1]["file_path"]).read_text(encoding="utf-8-sig")
    assert "FIRST_SOURCE_MARKER" in first_content
    assert "SECOND_SOURCE_MARKER" not in first_content
    assert "SECOND_SOURCE_MARKER" in second_content
    assert "FIRST_SOURCE_MARKER" not in second_content

    zip_path = structured_service.build_job_export_zip(owner_id="tenant_a", job_id="same_name_job", store=store)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("quality-report.json"))
    for filename in filenames:
        assert names.count(filename) == 1
    manifest_filenames = {item["filename"] for item in manifest["exports"]}
    summary_filenames = {item["summary"]["export_filename"] for item in manifest["exports"]}
    assert set(filenames) <= manifest_filenames
    assert set(filenames) <= summary_filenames


def test_dataset_list_marks_only_reviewed_policy_as_reviewed(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_csv(csv_path)

    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    listed = store.list_datasets(owner_id="tenant_a")
    assert listed[0]["profile_updated_at"] is None
    assert listed[0]["policy_updated_at"] is None
    assert listed[0]["policy_reviewed_at"] is None

    profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
    listed = store.list_datasets(owner_id="tenant_a")
    assert listed[0]["profile_updated_at"] is not None
    assert listed[0]["policy_updated_at"] is not None
    assert listed[0]["policy_reviewed_at"] is None

    structured_service.save_policy(
        dataset_id,
        owner_id="tenant_a",
        columns=structured_service.default_policy(profile)["columns"],
        store=store,
    )
    listed = store.list_datasets(owner_id="tenant_a")
    assert listed[0]["policy_reviewed_at"] is not None


def test_save_policy_requires_exact_dataset_schema_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "JWT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: False)

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_demo_customer_csv(csv_path)
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
    columns = structured_service.default_policy(profile)["columns"]

    saved = structured_service.save_policy(dataset_id, owner_id="tenant_a", columns=columns, store=store)
    assert saved["reviewed_at"]

    with pytest.raises(ValueError, match="missing columns"):
        structured_service.save_policy(dataset_id, owner_id="tenant_a", columns=columns[:-1], store=store)

    with pytest.raises(ValueError, match="unknown columns"):
        structured_service.save_policy(
            dataset_id,
            owner_id="tenant_a",
            columns=[*columns, {"column": "not_in_dataset", "action": "keep", "entity_type": "CUSTOM", "enabled": False, "params": {}}],
            store=store,
        )

    with pytest.raises(ValueError, match="duplicate columns"):
        structured_service.save_policy(dataset_id, owner_id="tenant_a", columns=[*columns, columns[0]], store=store)


def test_sqlite_connection_registers_datasets_with_owner_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))

    db_path = tmp_path / "source.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE customers (id INTEGER, phone TEXT, amount TEXT)")
        conn.execute("INSERT INTO customers VALUES (1, '13800138000', '1000')")
        conn.commit()

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    connection = structured_service.create_connection(
        owner_id="tenant_a",
        payload={
            "engine": "sqlite",
            "display_name": "Local SQLite",
            "sqlite_path": str(db_path),
            "password": "not stored in metadata",
        },
        store=store,
    )
    assert connection["metadata"]["dataset_count"] == 1
    assert connection["metadata"]["sqlite_path"] == str(db_path)
    assert connection["metadata"]["target"] == str(db_path)
    assert "password" not in connection["metadata"]

    discovered = structured_service.discover_connection_datasets(
        connection["id"],
        owner_id="tenant_a",
        store=store,
    )
    assert any(item["table_name"] == "customers" for item in discovered)

    registered = structured_service.register_connection_datasets(
        connection["id"],
        owner_id="tenant_a",
        selections=[{"table_name": "customers"}],
        store=store,
    )
    assert len(registered) == 1
    assert store.get_dataset(registered[0]["id"], owner_id="tenant_b") is None


def test_deleting_connection_removes_registered_tables_without_cross_tenant_leakage(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: False)

    db_path = tmp_path / "shared_source.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE customers (id INTEGER, phone TEXT, email TEXT)")
        conn.execute("INSERT INTO customers VALUES (1, '13800138000', 'alice@example.com')")
        conn.commit()

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))

    tenant_a_connection = structured_service.create_connection(
        owner_id="tenant_a",
        payload={
            "engine": "sqlite",
            "display_name": "Tenant A SQLite",
            "sqlite_path": str(db_path),
        },
        store=store,
    )
    tenant_a_dataset = structured_service.register_connection_datasets(
        tenant_a_connection["id"],
        owner_id="tenant_a",
        selections=[{"table_name": "customers"}],
        store=store,
    )[0]
    tenant_a_profile = structured_service.profile_dataset(tenant_a_dataset["id"], owner_id="tenant_a", store=store)
    structured_service.save_policy(
        tenant_a_dataset["id"],
        owner_id="tenant_a",
        columns=structured_service.default_policy(tenant_a_profile)["columns"],
        store=store,
    )

    tenant_b_connection = structured_service.create_connection(
        owner_id="tenant_b",
        payload={
            "engine": "sqlite",
            "display_name": "Tenant B SQLite",
            "sqlite_path": str(db_path),
        },
        store=store,
    )
    tenant_b_dataset = structured_service.register_connection_datasets(
        tenant_b_connection["id"],
        owner_id="tenant_b",
        selections=[{"table_name": "customers"}],
        store=store,
    )[0]

    assert store.delete_connection(tenant_a_connection["id"], owner_id="tenant_a") is True

    assert store.get_connection(tenant_a_connection["id"], owner_id="tenant_a") is None
    assert store.get_dataset(tenant_a_dataset["id"], owner_id="tenant_a") is None
    assert store.get_profile(tenant_a_dataset["id"], owner_id="tenant_a") is None
    assert store.get_policy(tenant_a_dataset["id"], owner_id="tenant_a") is None
    assert store.list_datasets(owner_id="tenant_a") == []

    assert store.get_connection(tenant_b_connection["id"], owner_id="tenant_b") is not None
    assert store.get_dataset(tenant_b_dataset["id"], owner_id="tenant_b") is not None
    assert len(store.list_datasets(owner_id="tenant_b")) == 1


def test_job_store_accepts_structured_batch(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    job_id = store.create_job(job_type=JobType.STRUCTURED_BATCH, owner_id="tenant_a")
    item_id = store.add_item(job_id, "dataset_1")

    job = store.get_job(job_id)
    item = store.get_item(item_id)
    assert job and job["job_type"] == "structured_batch"
    assert item and item["file_id"] == "dataset_1"


def test_structured_job_submit_enqueues_structured_task(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    csv_path = tmp_path / "customers.csv"
    _write_csv(csv_path)

    structured_store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=structured_store,
    )
    dataset_id = result["datasets"][0]["id"]
    job_store = JobStore(str(tmp_path / "jobs.sqlite3"))
    enqueued: list[dict[str, str]] = []
    monkeypatch.setattr(structured_store_module, "get_structured_store", lambda: structured_store)
    monkeypatch.setattr(
        job_service,
        "enqueue_task",
        lambda task_type, job_id, item_id, file_id, meta=None: enqueued.append(
            {"task_type": task_type, "job_id": job_id, "item_id": item_id, "file_id": file_id}
        ),
    )

    job = job_service.create_job(
        store=job_store,
        job_type_str="structured_batch",
        title="Structured",
        config={"dataset_ids": [dataset_id], "export_format": "csv"},
        skip_item_review=True,
        priority=0,
        owner_id="tenant_a",
    )
    job_service.add_item(job_store, job["id"], dataset_id, 0)
    submitted = job_service.submit_job(job_store, job["id"])

    assert submitted["status"] == "queued"
    assert enqueued == [
        {
            "task_type": "structured",
            "job_id": job["id"],
            "item_id": enqueued[0]["item_id"],
            "file_id": dataset_id,
        }
    ]


def test_structured_api_upload_is_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_csv(csv_path)

    test_app = FastAPI()
    test_app.include_router(
        structured_api.router,
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    test_app.dependency_overrides[get_structured_store] = lambda: store
    test_app.dependency_overrides[require_auth] = lambda: "tenant_a"
    try:
        with TestClient(test_app) as client:
            with csv_path.open("rb") as fh:
                response = client.post(
                    "/api/v1/structured/files",
                    files={"file": ("customers.csv", fh, "text/csv")},
                )
            assert response.status_code == 200
            assert response.json()["datasets"]

            assert client.get("/api/v1/structured/datasets").json()["datasets"]

            test_app.dependency_overrides[require_auth] = lambda: "tenant_b"
            assert client.get("/api/v1/structured/datasets").json()["datasets"] == []
    finally:
        test_app.dependency_overrides.clear()


def test_structured_api_get_policy_restores_saved_policy_and_is_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_csv(csv_path)

    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
    columns = structured_service.default_policy(profile)["columns"]
    columns[0]["action"] = "hash"
    columns[0]["enabled"] = True
    structured_service.save_policy(dataset_id, owner_id="tenant_a", columns=columns, store=store)

    test_app = FastAPI()
    test_app.include_router(
        structured_api.router,
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    test_app.dependency_overrides[get_structured_store] = lambda: store
    test_app.dependency_overrides[require_auth] = lambda: "tenant_a"
    try:
        with TestClient(test_app) as client:
            response = client.get(f"/api/v1/structured/datasets/{dataset_id}/policy")
            assert response.status_code == 200
            body = response.json()
            assert body["columns"][0]["action"] == "hash"
            assert body["columns"][0]["enabled"] is True
            assert body["updated_at"]

            test_app.dependency_overrides[require_auth] = lambda: "tenant_b"
            forbidden = client.get(f"/api/v1/structured/datasets/{dataset_id}/policy")
            assert forbidden.status_code == 404
    finally:
        test_app.dependency_overrides.clear()


def test_structured_api_rejects_policy_schema_mismatch_as_bad_request(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(structured_service, "has_text_semantic_ready", lambda: False)

    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_demo_customer_csv(csv_path)
    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
    columns = structured_service.default_policy(profile)["columns"]

    test_app = FastAPI()
    test_app.include_router(
        structured_api.router,
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    test_app.dependency_overrides[get_structured_store] = lambda: store
    test_app.dependency_overrides[require_auth] = lambda: "tenant_a"
    try:
        with TestClient(test_app) as client:
            invalid = client.put(
                f"/api/v1/structured/datasets/{dataset_id}/policy",
                json={"columns": columns[:-1]},
            )
            assert invalid.status_code == 400
            assert "missing columns" in invalid.json()["detail"]

            missing_dataset = client.put(
                "/api/v1/structured/datasets/not-a-dataset/policy",
                json={"columns": columns},
            )
            assert missing_dataset.status_code == 404
    finally:
        test_app.dependency_overrides.clear()


def test_structured_api_requires_reviewed_policy_before_job_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(structured_service.settings, "OUTPUT_DIR", str(tmp_path / "output"))
    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    job_store = JobStore(str(tmp_path / "jobs.sqlite3"))
    csv_path = tmp_path / "customers.csv"
    _write_csv(csv_path)

    result = structured_service.register_file_source(
        owner_id="tenant_a",
        filename="customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    enqueued: list[dict[str, str]] = []
    monkeypatch.setattr(structured_store_module, "get_structured_store", lambda: store)
    monkeypatch.setattr(
        job_service,
        "enqueue_task",
        lambda task_type, job_id, item_id, file_id, meta=None: enqueued.append(
            {"task_type": task_type, "job_id": job_id, "item_id": item_id, "file_id": file_id}
        ),
    )

    test_app = FastAPI()
    test_app.include_router(
        structured_api.router,
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    test_app.dependency_overrides[get_structured_store] = lambda: store
    test_app.dependency_overrides[get_job_store] = lambda: job_store
    test_app.dependency_overrides[require_auth] = lambda: "tenant_a"
    try:
        with TestClient(test_app) as client:
            blocked = client.post(
                "/api/v1/structured/jobs",
                json={"title": "blocked", "dataset_ids": [dataset_id], "export_format": "csv"},
            )
            assert blocked.status_code == 400
            assert "保存字段策略" in blocked.json()["detail"]

            profile = structured_service.profile_dataset(dataset_id, owner_id="tenant_a", store=store)
            structured_service.save_policy(
                dataset_id,
                owner_id="tenant_a",
                columns=structured_service.default_policy(profile)["columns"],
                store=store,
            )

            duplicate = client.post(
                "/api/v1/structured/jobs",
                json={"title": "duplicate", "dataset_ids": [dataset_id, dataset_id], "export_format": "csv"},
            )
            assert duplicate.status_code == 400
            assert "数据集不能重复选择" in duplicate.json()["detail"]
            assert "customers.csv" in duplicate.json()["detail"]
            assert dataset_id not in duplicate.json()["detail"]
            assert enqueued == []

            created = client.post(
                "/api/v1/structured/jobs",
                json={"title": "ready", "dataset_ids": [dataset_id], "export_format": "csv"},
            )
            assert created.status_code == 200
            assert created.json()["job"]["status"] == "queued"
            assert enqueued and enqueued[0]["file_id"] == dataset_id
    finally:
        test_app.dependency_overrides.clear()


def test_structured_api_discovers_sqlite_connection_datasets(tmp_path, monkeypatch):
    monkeypatch.setattr(structured_service.settings, "DATA_DIR", str(tmp_path / "data"))
    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    db_path = tmp_path / "customers.sqlite"
    _write_demo_customer_sqlite(db_path)

    test_app = FastAPI()
    test_app.include_router(
        structured_api.router,
        prefix="/api/v1",
        dependencies=[Depends(require_auth)],
    )
    test_app.dependency_overrides[get_structured_store] = lambda: store
    test_app.dependency_overrides[require_auth] = lambda: "tenant_a"
    try:
        with TestClient(test_app) as client:
            created = client.post(
                "/api/v1/structured/connections",
                json={
                    "engine": "sqlite",
                    "display_name": "Customer warehouse",
                    "sqlite_path": str(db_path),
                },
            )
            assert created.status_code == 200
            connection_id = created.json()["id"]

            response = client.get(f"/api/v1/structured/connections/{connection_id}/datasets")
            assert response.status_code == 200
            datasets = response.json()["datasets"]
            assert len(datasets) == 1
            assert datasets[0]["id"].startswith("discovered:")
            assert datasets[0]["connection_id"] == connection_id
            assert datasets[0]["source_id"] is None
            assert datasets[0]["created_at"]
            assert datasets[0]["table_name"] == "customers"
            assert datasets[0]["column_count"] == 7
    finally:
        test_app.dependency_overrides.clear()


def test_delete_dataset_cascades_and_isolates_owner(tmp_path):
    """PM 需求：文件表逐数据集删除。级联策略/画像、越权 404、幂等。"""
    store = StructuredStore(str(tmp_path / "structured.sqlite3"))
    csv_path = tmp_path / "demo_customers.csv"
    _write_demo_customer_csv(csv_path)
    result = structured_service.register_file_source(
        owner_id="admin",
        filename="demo_customers.csv",
        file_path=str(csv_path),
        kind="csv",
        store=store,
    )
    dataset_id = result["datasets"][0]["id"]
    structured_service.profile_dataset(dataset_id, owner_id="admin", store=store)

    # 他人无法删除，数据仍在
    assert store.delete_dataset(dataset_id, owner_id="intruder") is False
    assert any(d["id"] == dataset_id for d in store.list_datasets(owner_id="admin"))

    # 本主删除成功，列表消失，重复删除幂等返回 False
    assert store.delete_dataset(dataset_id, owner_id="admin") is True
    assert all(d["id"] != dataset_id for d in store.list_datasets(owner_id="admin"))
    assert store.delete_dataset(dataset_id, owner_id="admin") is False
