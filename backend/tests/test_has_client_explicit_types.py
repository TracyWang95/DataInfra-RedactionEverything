"""回归: HaS NER 清单必须显式传入——LEGAL_ENTITY_TYPES 隐藏默认词表已删除。"""
import pytest

from app.services.has_client import HaSClient


def test_normalize_ner_types_rejects_missing_checklist():
    with pytest.raises(ValueError):
        HaSClient._normalize_ner_types(None)
    with pytest.raises(ValueError):
        HaSClient._normalize_ner_types([])


def test_normalize_ner_types_keeps_explicit_checklist():
    assert HaSClient._normalize_ner_types(["姓名", "姓名", "地址"]) == ["姓名", "地址"]


def test_legal_entity_types_vocabulary_is_gone():
    assert not hasattr(HaSClient, "LEGAL_ENTITY_TYPES")
