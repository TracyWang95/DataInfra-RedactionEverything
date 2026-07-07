"""自定义图像文字识别项（custom_*）必须以用户起的名称进 HaS 查询，并映射回自身 id。

回归背景（2026-07-02 双卡 5090 测试反馈）：简历"薪酬/年龄（岁）"、医疗报告
"检查号/科室号"等自定义项死活识别不出——查询标签被 canonical_type_id 大写成
CUSTOM_OCR_HAS_XXX 乱码，开放词表的 HaS 模型对乱码标签只能返回空桶；
用户名称与描述均未进 prompt。内置项走注册表中文名，不受影响。
"""

import asyncio
from dataclasses import dataclass, field

from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.has_text_payload import (
    _build_has_text_type_names,
    _canonical_image_text_type,
)
from app.services.vision.ocr_pipeline import match_entities_to_ocr, run_has_text_analysis


@dataclass
class _TypeConfig:
    id: str
    name: str
    description: str = ""
    examples: list = field(default_factory=list)


SALARY_TYPE = _TypeConfig(id="custom_ocr_has_mr1v6ogy", name="薪酬")
AGE_TYPE = _TypeConfig(id="custom_ocr_has_ab12cd34", name="年龄（岁）")
PERSON_TYPE = _TypeConfig(id="PERSON", name="姓名")


class _StubHaSClient:
    """最小 HaS 客户端替身：记录收到的查询标签并返回固定桶。"""

    def __init__(self, result):
        self.result = result
        self.requested_types = None

    def ner(self, text, entity_types=None, **kwargs):
        self.requested_types = list(entity_types or [])
        return dict(self.result)


def test_custom_type_query_labels_use_display_name():
    labels = _build_has_text_type_names([PERSON_TYPE, SALARY_TYPE, AGE_TYPE])
    assert "薪酬" in labels
    assert "年龄（岁）" in labels
    assert all(not label.upper().startswith("CUSTOM_") for label in labels)
    # 内置项仍走注册表中文名
    assert "姓名" in labels


def test_canonical_image_text_type_preserves_custom_ids():
    assert _canonical_image_text_type("custom_ocr_has_mr1v6ogy") == "custom_ocr_has_mr1v6ogy"
    # 途中被大写过的 custom id 也要还原（match 环节有 entity_type.upper()）
    assert _canonical_image_text_type("CUSTOM_OCR_HAS_MR1V6OGY") == "custom_ocr_has_mr1v6ogy"
    assert _canonical_image_text_type("PERSON") == "PERSON"


def _resume_blocks():
    # 真实简历版式的关键行（智联导出 PDF 文字层，简历详情-焦先生）
    lines = [
        "焦先生",
        "男",
        "36岁 (1988年4月)",
        "求职期望",
        "咨询项目经理 2.8万-3.5万/月",
        "芬碳资产管理咨询（北京）有限公司",
        "咨询项目管理 （咨询项目经理）",
        "10K-15K/月",
        "2015.05 - 2016.04 (11个月)",
    ]
    blocks = []
    for i, line in enumerate(lines):
        top = 40 * i
        width = 24 * max(1, len(line))
        blocks.append(
            OCRTextBlock(
                text=line,
                polygon=[[0, top], [width, top], [width, top + 30], [0, top + 30]],
            )
        )
    return blocks


def test_run_has_text_analysis_queries_names_and_maps_back_to_custom_ids():
    client = _StubHaSClient({
        "薪酬": ["2.8万-3.5万/月", "10K-15K/月"],
        "年龄（岁）": ["36岁"],
        "姓名": ["焦先生"],
    })
    entities = asyncio.run(
        run_has_text_analysis(
            _resume_blocks(),
            client,
            vision_types=[PERSON_TYPE, SALARY_TYPE, AGE_TYPE],
        )
    )

    # 发出去的查询标签是用户名称，不是大写 id
    assert client.requested_types is not None
    assert "薪酬" in client.requested_types
    assert "年龄（岁）" in client.requested_types
    assert all(not t.upper().startswith("CUSTOM_") for t in client.requested_types)

    # 返回实体的 type 是自定义项自己的 id（与文本链路一致的小写原始 id）
    by_type = {}
    for entity in entities:
        by_type.setdefault(entity["type"], []).append(entity["text"])
    assert by_type.get("custom_ocr_has_mr1v6ogy") == ["2.8万-3.5万/月", "10K-15K/月"]
    assert by_type.get("custom_ocr_has_ab12cd34") == ["36岁"]
    assert by_type.get("PERSON") == ["焦先生"]


def test_match_entities_to_ocr_keeps_custom_type_on_regions():
    blocks = _resume_blocks()
    entities = [
        {"type": "custom_ocr_has_mr1v6ogy", "text": "10K-15K/月"},
        {"type": "custom_ocr_has_ab12cd34", "text": "36岁"},
    ]
    regions = match_entities_to_ocr(blocks, entities)
    types = {region.entity_type for region in regions}
    assert "custom_ocr_has_mr1v6ogy" in types
    assert "custom_ocr_has_ab12cd34" in types
