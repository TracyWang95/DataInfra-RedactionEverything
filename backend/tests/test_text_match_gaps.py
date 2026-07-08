"""Tests for the text-pipeline detection gap fixes:

1. one value printed in several places attaches to every containing block;
2. a value never attaches to a block that does not actually contain it
   (chars-verified authoritative text; fuzzy runs only when nothing exact);
3. new atomic types OCCUPATION / POSTAL_CODE / CERT_NO / NATIVE_PLACE;
4. DOCUMENT_NUMBER form-field label recall (标签：值 / label-cell layouts).
"""
import asyncio
import time
from types import SimpleNamespace

from app.models.type_mapping import (
    TYPE_ID_TO_CN,
    canonical_type_id,
)
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.pipeline_service import PRESET_OCR_HAS_TYPES
from app.services.vision.has_text_payload import _build_has_text_type_names
from app.services.vision.ocr_pipeline import (
    match_entities_to_ocr,
    run_has_text_analysis,
)


def _block(text: str, left: int, top: int, width: int = 160, height: int = 20, chars=None) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        polygon=[[left, top], [left + width, top], [left + width, top + height], [left, top + height]],
        confidence=0.98,
        chars=chars or [],
    )


def _token_chars(tokens: list[str], left: int, top: int, height: int = 20) -> list[dict]:
    boxes = []
    cursor = left
    for token in tokens:
        token_width = 10 * max(1, len(token))
        boxes.append({"c": token, "x1": cursor, "y1": top, "x2": cursor + token_width, "y2": top + height})
        cursor += token_width
    return boxes


# ---------------------------------------------------------------------------
# Gap 1: same value in several blocks -> a region on every containing block
# ---------------------------------------------------------------------------

def test_same_value_attaches_to_every_containing_block() -> None:
    code = "91310115MA1K3X3B9L"
    blocks = [
        _block(code, 130, 170),
        _block(code, 130, 270),
    ]

    regions = match_entities_to_ocr(blocks, [{"type": "CREDIT_CODE", "text": code}])

    assert sorted(region.top for region in regions) == [170, 270]


def test_fuzzy_match_never_shadows_a_later_exact_occurrence() -> None:
    # The customs declaration case: the first physical copy was OCR-misread
    # (missing one char), the second copy is exact. The old in-loop fuzzy
    # matched the misread block first and `break`-ed past the exact block.
    misread = _block("91310115MA1K3X3BL", 130, 170)
    exact = _block("91310115MA1K3X3B9L", 130, 270)

    regions = match_entities_to_ocr(
        [misread, exact],
        [
            {"type": "CREDIT_CODE", "text": "91310115MA1K3X3B9L"},
            {"type": "CREDIT_CODE", "text": "91310115MA1K3X3BL"},
        ],
    )

    assert {region.top for region in regions} == {170, 270}
    exact_region = next(region for region in regions if region.top == 270)
    assert exact_region.source == "text_match"


# ---------------------------------------------------------------------------
# Gap 2: a value never attaches to a block that does not contain it
# ---------------------------------------------------------------------------

def test_value_never_attaches_to_block_whose_chars_disprove_its_text() -> None:
    # PP-StructureV3 pathology: a duplicated box carries another box's text
    # label, while its char boxes still spell the box's real content.
    lying = _block(
        "597,000.00", 260, 740, chars=_token_chars(["内存", "：", "256GB", "DDR4"], 260, 740),
    )
    true_amount = _block(
        "597,000.00", 880, 740, width=90, chars=_token_chars(["597,000.00"], 880, 740),
    )

    regions = match_entities_to_ocr(
        [lying, true_amount],
        [{"type": "AMOUNT", "text": "597,000.00"}],
    )

    assert [region.left for region in regions] == [880]


def test_incomplete_char_list_does_not_disprove_block_text() -> None:
    # The service sometimes drops leading char boxes (chars spell 9,000.00
    # under text 89,000.00). A chars substring is partial evidence of the same
    # content, not a contradiction — the block still matches by its text.
    partial_chars = _block(
        "89,000.00", 596, 906, width=80, chars=_token_chars(["9", ",", "000.00"], 606, 906),
    )

    regions = match_entities_to_ocr(
        [partial_chars],
        [{"type": "AMOUNT", "text": "89,000.00"}],
    )

    assert [(region.left, region.width) for region in regions] == [(596, 80)]


def test_equal_length_char_reading_variant_keeps_block_text() -> None:
    # The char-level recognizer can read the same glyphs differently
    # (× vs X). An equal-length divergence is a reading variant of the same
    # content, not another box's text, so the block still matches by its text.
    variant = _block(
        "江苏省XX市XX区XX路88号", 169, 210, width=209,
        chars=_token_chars(list("江苏省×X市×X区×X路88号"), 169, 210),
    )

    regions = match_entities_to_ocr(
        [variant],
        [{"type": "ADDRESS", "text": "江苏省XX市XX区XX路88号"}],
    )

    assert [region.left for region in regions] == [169]


def test_amount_value_display_variants_match_by_signature() -> None:
    cell = _block("￥1,431,400.00元", 700, 100)
    running_text = _block("合同总金额按附件执行1431400相关", 100, 300)

    regions = match_entities_to_ocr(
        [cell, running_text],
        [{"type": "AMOUNT", "text": "1431400，00"}],
    )

    assert [region.left for region in regions] == [700]


def test_short_value_attaches_by_equality_or_isolated_token_only() -> None:
    cell = _block("男", 450, 110, width=24)
    labelled = _block("性别：男", 380, 210)
    inside_word = _block("男科门诊", 100, 310)

    regions = match_entities_to_ocr(
        [cell, labelled, inside_word],
        [{"type": "GENDER", "text": "男"}],
    )

    assert sorted(region.top for region in regions) == [110, 210]


# ---------------------------------------------------------------------------
# Value-level crop: a 标签：值 row keeps the value's char-box x span, full row height
# ---------------------------------------------------------------------------

def test_value_level_crop_narrows_x_keeps_full_row_height() -> None:
    # A whole-line OCR block "甲方（采购方）：北京智算科技有限公司" with aligned
    # per-character boxes. The ORG value occupies only the right part of the
    # line; the box must cover the value's character span in x and keep the
    # block's full vertical extent (705318c), not collapse to the char-y union.
    label = "甲方（采购方）："
    value = "北京智算科技有限公司"
    text = label + value
    block = _block(
        text, 40, 168, height=20,
        chars=_token_chars(list(text), 40, 168, height=20),
    )
    # The whole block spans 40 .. 40 + 10*len(text); the value starts after the
    # label, so its left edge is the label's pixel width past the block left.
    value_left = 40 + 10 * len(label)
    value_right = 40 + 10 * len(text)

    regions = match_entities_to_ocr(
        [block], [{"type": "INSTITUTION_NAME", "text": value}],
    )

    assert len(regions) == 1
    region = regions[0]
    # x cropped to the value's character-box union (label excluded).
    assert region.left == value_left
    assert region.left + region.width == value_right
    assert region.left > block.left  # strictly narrower than the whole line
    # y/height stay the block's full row height.
    assert region.top == block.top
    assert region.height == block.height


def test_value_level_crop_falls_back_to_whole_block_without_chars() -> None:
    # No char boxes (e.g. a PaddleOCR-VL coarse multi-value line): the safety net
    # masks the whole block rather than estimate a sub-span.
    text = "法定代表人/授权代表（签字）：张伟"
    block = _block(text, 40, 1360, width=380, height=24)

    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": "张伟"}])

    assert len(regions) == 1
    region = regions[0]
    assert (region.left, region.top, region.width, region.height) == (
        block.left, block.top, block.width, block.height,
    )


# ---------------------------------------------------------------------------
# Gap 3: new atomic types
# ---------------------------------------------------------------------------

def test_new_atomic_types_registered() -> None:
    assert canonical_type_id("OCCUPATION") == "OCCUPATION"
    assert canonical_type_id("POSTAL_CODE") == "POSTAL_CODE"  # no longer an ADDRESS alias
    assert canonical_type_id("CERT_NO") == "CERT_NO"
    assert canonical_type_id("NATIVE_PLACE") == "NATIVE_PLACE"
    assert TYPE_ID_TO_CN["OCCUPATION"] == "职业"
    assert TYPE_ID_TO_CN["POSTAL_CODE"] == "邮政编码"
    assert TYPE_ID_TO_CN["CERT_NO"] == "证号"
    assert TYPE_ID_TO_CN["NATIVE_PLACE"] == "籍贯"


def test_new_atomic_types_in_pipeline_presets_not_default_enabled() -> None:
    by_id = {item.id: item for item in PRESET_OCR_HAS_TYPES}
    for type_id in ("OCCUPATION", "POSTAL_CODE", "CERT_NO", "NATIVE_PLACE"):
        assert type_id in by_id, type_id
        assert by_id[type_id].default_enabled is False


def test_new_atomic_types_send_chinese_labels_to_has() -> None:
    vision_types = [
        SimpleNamespace(id="OCCUPATION", name="职业"),
        SimpleNamespace(id="POSTAL_CODE", name="邮政编码"),
        SimpleNamespace(id="CERT_NO", name="证号"),
        SimpleNamespace(id="NATIVE_PLACE", name="籍贯"),
    ]
    assert _build_has_text_type_names(vision_types) == ["职业", "邮政编码", "证号", "籍贯"]


# ---------------------------------------------------------------------------
# Gap 4: DOCUMENT_NUMBER form-field label recall
# ---------------------------------------------------------------------------
