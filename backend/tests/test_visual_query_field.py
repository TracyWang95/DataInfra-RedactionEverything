"""视觉链 checklist row 的 query 字段: 显示语义(rule)与模型查询词(query)分离.

0712 医院CT报告单实证: LA 对中文短语"手写签名或手写姓名"把影像号下的手写下划线
框成签字。A/B 矩阵(5 措辞 × 4 真值图 × 2 轮)当时选出 "handwritten name signature"。

0717 病例5 复盘推翻了那个措辞: 查询词里的 "name" 把 LA 往印刷姓名上带、饿死手写
召回(中间医生手写签字单采样只中 2/6)。去掉 name 改 "handwritten signature" 后
单采样 4-5/6, 全语料 34 图 0 漏。出厂预设按新措辞发, 本测试锚的是新值 —— 旧值是
已知会漏 PII 的措辞, 不要再改回去。
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
    assert first_row.get("query") == "handwritten signature"
    # display wording stays Chinese for the UI
    assert first_row.get("rule") == "手写签名或手写姓名"
