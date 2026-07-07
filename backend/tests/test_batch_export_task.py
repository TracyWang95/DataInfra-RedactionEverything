"""批量异步分卷导出引擎（export_service）核心语义。

背景（2026-07 万级文件导出）：旧 build_batch_zip 在内存攒整包，1 万文件
必炸。新引擎：分卷写磁盘（内存 O(1)）、已压缩格式 ZIP_STORED 免重压缩、
manifest 汇总、预估大小 ≈ st_size 求和。
"""

import asyncio
import json
import os
import zipfile

from app.services import export_service


def _make_entries(tmp_path, count: int, size: int, ext: str = ".txt"):
    entries = []
    for i in range(count):
        p = tmp_path / f"src_{i:04d}{ext}"
        p.write_bytes(b"x" * size)
        entries.append((str(p), f"file_{i:04d}{ext}", size))
    return entries


def _run_volumes(tmp_path, entries, **kw):
    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    manifest = {"note": "test"}
    volumes = export_service.write_export_volumes(
        entries, str(out_dir), manifest, progress_cb=lambda **_: None, **kw
    )
    return out_dir, volumes


def test_volumes_split_by_file_count(tmp_path):
    entries = _make_entries(tmp_path, 25, 100)
    out_dir, volumes = _run_volumes(tmp_path, entries, max_files_per_volume=10, max_bytes_per_volume=10**9)
    assert [v["file_count"] for v in volumes] == [10, 10, 5]
    names = set()
    for v in volumes:
        with zipfile.ZipFile(out_dir / v["name"]) as zf:
            names.update(n for n in zf.namelist() if n != "manifest.json")
    assert len(names) == 25
    # manifest.json 在末卷
    with zipfile.ZipFile(out_dir / volumes[-1]["name"]) as zf:
        assert "manifest.json" in zf.namelist()


def test_volumes_split_by_bytes_and_oversize_file_gets_own_volume(tmp_path):
    entries = _make_entries(tmp_path, 3, 600_000)  # 0.6MB × 3, 卷上限 1MB
    out_dir, volumes = _run_volumes(tmp_path, entries, max_files_per_volume=100, max_bytes_per_volume=1_000_000)
    assert all(v["file_count"] <= 2 for v in volumes)
    # 单文件超过卷上限：独占一卷、不死循环
    big = _make_entries(tmp_path, 1, 2_000_000, ext=".bin")
    out_dir2 = tmp_path / "out2"
    out_dir2.mkdir()
    volumes2 = export_service.write_export_volumes(
        big, str(out_dir2), {}, progress_cb=lambda **_: None,
        max_files_per_volume=100, max_bytes_per_volume=1_000_000,
    )
    assert len(volumes2) == 1 and volumes2[0]["file_count"] == 1


def test_precompressed_formats_are_stored_not_deflated(tmp_path):
    entries = _make_entries(tmp_path, 1, 1000, ext=".jpg") + _make_entries(tmp_path, 1, 1000, ext=".txt")
    # 两个 entry 名字冲突了吗？_make_entries 用同 index 前缀——改名区分
    entries = [
        (entries[0][0], "photo.jpg", 1000),
        (entries[1][0], "note.txt", 1000),
    ]
    out_dir, volumes = _run_volumes(tmp_path, entries)
    with zipfile.ZipFile(out_dir / volumes[0]["name"]) as zf:
        by_name = {i.filename: i.compress_type for i in zf.infolist()}
    assert by_name["photo.jpg"] == zipfile.ZIP_STORED
    assert by_name["note.txt"] == zipfile.ZIP_DEFLATED


def test_manifest_written_and_volume_sizes_reported(tmp_path):
    entries = _make_entries(tmp_path, 5, 512)
    out_dir, volumes = _run_volumes(tmp_path, entries)
    assert len(volumes) == 1
    v = volumes[0]
    assert v["size_bytes"] == os.path.getsize(out_dir / v["name"])
    with zipfile.ZipFile(out_dir / v["name"]) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["note"] == "test"


def test_missing_source_file_raises_and_reports(tmp_path):
    entries = _make_entries(tmp_path, 3, 100)
    os.remove(entries[1][0])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    try:
        export_service.write_export_volumes(
            entries, str(out_dir), {}, progress_cb=lambda **_: None
        )
        raise AssertionError("missing source must raise")
    except FileNotFoundError:
        pass


def test_manager_submit_runs_persists_and_guards_paths(tmp_path, monkeypatch):
    """端到端跑一次 submit（曾因运行时 ImportError 只在真实请求里炸）。"""
    monkeypatch.setattr(export_service.settings, "OUTPUT_DIR", str(tmp_path))
    entries = _make_entries(tmp_path, 3, 100)

    async def main():
        manager = export_service.ExportTaskManager()
        task = manager.submit(
            "owner/委托方1",  # 含需安全化的字符
            "batch_files",
            export_service.make_batch_files_runner(entries, {"n": 1}),
            total_bytes=300,
            file_count=3,
        )
        for _ in range(200):
            if task.status in ("completed", "failed"):
                break
            await asyncio.sleep(0.02)
        return manager, task

    manager, task = asyncio.run(main())
    assert task.status == "completed", task.error
    assert task.volumes and os.path.exists(os.path.join(task.out_dir, "export-status.json"))
    assert manager.volume_path(task.export_id, "owner/委托方1", task.volumes[0]["name"])
    # 路径穿越与跨租户拒绝
    assert manager.volume_path(task.export_id, "owner/委托方1", "../evil.zip") is None
    assert manager.volume_path(task.export_id, "someone_else", task.volumes[0]["name"]) is None


def test_estimate_matches_actual_zip_size_closely(tmp_path):
    entries = _make_entries(tmp_path, 20, 4096, ext=".jpg")  # STORED → 几乎零压缩开销
    total = sum(size for _p, _a, size in entries)
    est = export_service.estimate_volumes(entries, max_files_per_volume=1000, max_bytes_per_volume=10**9)
    assert est["total_bytes"] == total
    assert est["file_count"] == 20
    assert est["estimated_volume_count"] == 1
    out_dir, volumes = _run_volumes(tmp_path, entries)
    actual = sum(v["size_bytes"] for v in volumes)
    assert abs(actual - total) / total < 0.05  # 归档开销 <5%（小文件下界宽些）
