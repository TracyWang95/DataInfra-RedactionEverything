"""视觉链 checklist row 的 query 字段: 显示语义(rule)与模型查询词(query)分离.

0712 医院CT报告单实证: LA 对中文短语"手写签名或手写姓名"把影像号下的手写下划线
框成签字(且在 tiff1 医生淡签名上漏检 0/0)。A/B 矩阵(5 措辞 × 4 真值图 × 2 轮)
选出 "handwritten name signature": CT报告 0/0(误报消除)、labor 1/1、house 4/4、
tiff1 1/1(比现状还多召回)。查询词换措辞是模型驱动手段——清单仍 owns vocabulary,
row.query 用户可编辑,rule 保持中文显示。
"""
import json
import os
from types import SimpleNamespace

from app.services.vision.locate_requests import _grounding_query

_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "preset_pipeline_types.json")


def _item(checklist=None, rules=None):
    return SimpleNamespace(checklist=checklist or [], rules=rules or [])


def test_row_query_field_wins_over_rule():
    item = _item(checklist=[{"rule": "手写签名或手写姓名", "query": "handwritten name signature"}])
    assert _grounding_query(item, "signature") == "handwritten name signature"


def test_row_without_query_falls_back_to_rule():
    item = _item(checklist=[{"rule": "手写签名或手写姓名"}])
    assert _grounding_query(item, "signature") == "手写签名或手写姓名"


def test_blank_query_is_ignored():
    item = _item(checklist=[{"rule": "手写签名或手写姓名", "query": "   "}])
    assert _grounding_query(item, "signature") == "手写签名或手写姓名"


def test_factory_signature_preset_ships_the_ab_validated_query():
    with open(_CONFIG, encoding="utf-8") as fh:
        presets = json.load(fh)
    signature = next(it for it in presets["visual_features"] if it.get("id") == "signature")
    first_row = (signature.get("checklist") or [{}])[0]
    assert first_row.get("query") == "handwritten name signature"
    # display wording stays Chinese for the UI
    assert first_row.get("rule") == "手写签名或手写姓名"
