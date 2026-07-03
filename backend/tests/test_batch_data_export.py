"""批量结果明细导出（P0-数据）：流式行生成器 + CSV 分卷 + summary_only。

10 万 item 的 job 只有一个全量 JSON 报告可导，后端内存组装+浏览器全量拉取
双双卡死；技术评测需要"每条结果一行"的可分析明细。此处钉住：
  - iter_report_file_rows / iter_entity_rows 逐行 yield（不攒全量）
  - write_csv_parts 按行数分卷、utf-8-sig
  - build_export_report(include_files=False) 聚合与全量版一致
"""

import csv
import io

import pytest

import app.services.job_management_service as jms
from app.services import export_service
from app.services.job_store import JobStore, JobType


def _fake_info(fid: str, entities: int = 2, boxes: int = 1) -> dict:
    return {
        "original_filename": f"{fid}.pdf",
        "file_type": "pdf",
        "file_size": 1234,
        "page_count": 3,
        "output_path": f"/outputs/{fid}.pdf",
        "entities": [
            {"text": f"张三{k}", "type": "PERSON", "page": 1, "start": k, "end": k + 3,
             "source": "has", "confidence": 0.95}
            for k in range(entities)
        ],
        "bounding_boxes": [
            {"type": "official_seal", "text": "公章", "page": 1, "x": 0.1, "y": 0.2,
             "width": 0.05, "height": 0.06, "source": "visual_features", "selected": True}
            for _ in range(boxes)
        ],
    }


@pytest.fixture()
def job_env(tmp_path, monkeypatch):
    store = JobStore(str(tmp_path / "jobs.sqlite3"))
    job_id = store.create_job(job_type=JobType.SMART_BATCH, owner_id="tenant_a")
    file_ids = [f"file_{i:04d}" for i in range(250)]
    for fid in file_ids:
        store.add_item(job_id, fid)
    infos = {fid: _fake_info(fid) for fid in file_ids}
    monkeypatch.setattr(jms, "_safe_file_info", lambda fid: (infos.get(fid), None))
    return store, job_id, file_ids


def test_iter_report_file_rows_matches_full_report(job_env):
    store, job_id, file_ids = job_env
    rows = list(jms.iter_report_file_rows(store, job_id))
    assert len(rows) == 250
    assert rows[0]["file_id"] == "file_0000"
    assert rows[0]["filename"] == "file_0000.pdf"
    assert rows[0]["entity_count"] == 3  # 2 entities + 1 selected box

    report = jms.build_export_report(store, job_id)
    assert len(report["files"]) == 250
    by_id = {f["file_id"]: f for f in report["files"]}
    for row in rows[:10]:
        assert row["entity_count"] == by_id[row["file_id"]]["entity_count"]
        assert row["status"] == by_id[row["file_id"]]["status"]


def test_summary_only_report_keeps_aggregates_drops_files(job_env):
    store, job_id, _ = job_env
    full = jms.build_export_report(store, job_id)
    slim = jms.build_export_report(store, job_id, include_files=False)
    assert slim["files"] == []
    assert slim["summary"] == full["summary"]
    assert slim["redacted_zip"] == full["redacted_zip"]


def test_iter_entity_rows_expands_entities_and_regions(job_env):
    store, job_id, _ = job_env
    rows = list(jms.iter_entity_rows(store, job_id, selected_file_ids=["file_0001"]))
    kinds = [r["record_kind"] for r in rows]
    assert kinds.count("entity") == 2
    assert kinds.count("region") == 1
    entity = next(r for r in rows if r["record_kind"] == "entity")
    assert entity["type"] == "PERSON" and entity["filename"] == "file_0001.pdf"
    region = next(r for r in rows if r["record_kind"] == "region")
    assert region["type"] == "official_seal" and region["page"] == 1


def test_write_csv_parts_splits_and_is_excel_friendly(tmp_path):
    headers = ["a", "b"]
    rows = ({"a": i, "b": f"值{i}"} for i in range(250))
    parts = export_service.write_csv_parts(
        rows, str(tmp_path), "files", headers, rows_per_part=100
    )
    assert [p["file_count"] for p in parts] == [100, 100, 50]
    assert parts[0]["name"] == "files-part001.csv"
    raw = (tmp_path / parts[0]["name"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM，Excel 直开
    with io.open(tmp_path / parts[2]["name"], encoding="utf-8-sig") as f:
        got = list(csv.DictReader(f))
    assert len(got) == 50 and got[0]["a"] == "200"


def test_write_csv_parts_single_part_has_no_suffix_pressure(tmp_path):
    rows = ({"a": i} for i in range(5))
    parts = export_service.write_csv_parts(rows, str(tmp_path), "entities", ["a"], rows_per_part=100)
    assert len(parts) == 1
    assert parts[0]["name"] == "entities-part001.csv"
