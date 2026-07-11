"""清单直传 (text chain): 勾选什么查什么 — the checklist owns the query
vocabulary end to end, no backend registry translation.

Before: a checked item's id went through TYPE_REGISTRY to become Chinese
query labels — a second, enumerated, silently-diverging vocabulary (健康信息
was secretly queried as 诊断; 案号 as 文书编号). Now the item itself carries
its labels: explicit query_labels (factory presets ship 金额+大写金额 so both
numeral renderings of a paired amount land in separate buckets), else the
user-facing name. The response is tagged by request, LA-style.
"""
from types import SimpleNamespace

from app.services.pipeline_service import PRESET_OCR_HAS_TYPES
from app.services.vision.has_text_payload import (
    _build_has_text_type_names,
    _default_has_text_items,
    _item_query_labels,
)


def _item(id: str, name: str, query_labels: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=id, name=name, query_labels=query_labels or [])


def test_checked_item_name_is_the_query() -> None:
    labels = _build_has_text_type_names([_item("PERSON", "姓名")])
    assert labels == ["姓名"]


def test_item_query_labels_override_name() -> None:
    labels = _build_has_text_type_names([_item("AMOUNT", "金额", ["金额", "大写金额"])])
    assert labels == ["金额", "大写金额"]


def test_renamed_item_queries_by_its_new_name() -> None:
    # WYSIWYG: the user renames the item -> the model is asked the new name,
    # no registry snaps it back to a canonical translation.
    labels = _build_has_text_type_names([_item("HEALTH_INFO", "体检结论")])
    assert labels == ["体检结论"]


def test_custom_item_unchanged() -> None:
    labels = _build_has_text_type_names([_item("custom_extension_jchk", "检查号")])
    assert labels == ["检查号"]


def test_factory_preset_carries_amount_dual_labels() -> None:
    amount = next(item for item in PRESET_OCR_HAS_TYPES if item.id == "AMOUNT")
    assert _item_query_labels(amount) == ["金额", "大写金额"]
    health = next(item for item in PRESET_OCR_HAS_TYPES if item.id == "HEALTH_INFO")
    assert _item_query_labels(health) == ["健康信息", "诊断"]


def test_default_checklist_comes_from_presets() -> None:
    items = _default_has_text_items()
    assert items, "default checklist must resolve from the preset file"
    labels = _build_has_text_type_names(None)
    # the default query set is built from preset item names/labels — spot-check
    assert "姓名" in labels and "金额" in labels and "大写金额" in labels
