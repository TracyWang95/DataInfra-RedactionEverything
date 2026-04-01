"""Tests for app.services.file_store_db -- SQLite-backed file store."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.file_store_db import FileStoreDB


@pytest.fixture
def store(tmp_path: Path) -> FileStoreDB:
    return FileStoreDB(str(tmp_path / "file_store.sqlite3"))


def test_set_and_get(store: FileStoreDB) -> None:
    data = {"filename": "test.pdf", "size": 1024}
    store.set("f1", data)
    result = store.get("f1")
    assert result is not None
    assert result["filename"] == "test.pdf"
    assert result["size"] == 1024


def test_get_missing_returns_none(store: FileStoreDB) -> None:
    assert store.get("nonexistent") is None


def test_contains(store: FileStoreDB) -> None:
    store.set("f1", {"name": "a"})
    assert "f1" in store
    assert "f2" not in store


def test_pop(store: FileStoreDB) -> None:
    store.set("f1", {"name": "a"})
    val = store.pop("f1")
    assert val is not None
    assert val["name"] == "a"
    assert store.get("f1") is None
    # Pop missing key returns default
    assert store.pop("f1", "default") == "default"


def test_clear(store: FileStoreDB) -> None:
    store.set("f1", {"a": 1})
    store.set("f2", {"b": 2})
    assert len(store) == 2
    store.clear()
    assert len(store) == 0


def test_update(store: FileStoreDB) -> None:
    store.update({
        "f1": {"name": "a"},
        "f2": {"name": "b"},
        "f3": {"name": "c"},
    })
    assert len(store) == 3
    assert store.get("f2")["name"] == "b"


def test_dict_compatibility(store: FileStoreDB) -> None:
    store.set("f1", {"x": 1})
    store.set("f2", {"x": 2})
    d = dict(store)
    assert set(d.keys()) == {"f1", "f2"}
    # dict(store) uses __iter__ + __getitem__
    assert d["f1"]["x"] == 1
    assert d["f2"]["x"] == 2


def test_items_values_keys(store: FileStoreDB) -> None:
    store.set("a", {"v": 1})
    store.set("b", {"v": 2})

    keys = store.keys()
    assert set(keys) == {"a", "b"}

    values = store.values()
    assert len(values) == 2
    vs = {v["v"] for v in values}
    assert vs == {1, 2}

    items = store.items()
    assert len(items) == 2
    item_dict = dict(items)
    assert item_dict["a"]["v"] == 1
    assert item_dict["b"]["v"] == 2
