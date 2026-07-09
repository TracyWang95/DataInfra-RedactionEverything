from PIL import Image

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.ocr_service import OCRItem
from app.services.vision.ocr_pipeline import (
    _clone_text_block,
    _dedupe_ocr_regions,
    _is_amount_format_text,
    _merge_ocr_blocks,
    match_entities_to_ocr,
    reconstruct_visual_line_blocks,
    run_paddle_ocr,
)


def test_visual_line_reconstruction_joins_split_ocr_text_generically() -> None:
    blocks = [
        OCRTextBlock(
            text="海南",
            polygon=[[100, 40], [140, 40], [140, 70], [100, 70]],
            confidence=0.98,
        ),
        OCRTextBlock(
            text="工程服务有限公司",
            polygon=[[175, 38], [320, 38], [320, 70], [175, 70]],
            confidence=0.98,
        ),
    ]

    reconstructed = reconstruct_visual_line_blocks(blocks)

    assert [block.text for block in reconstructed] == ["海南工程服务有限公司"]


def test_visual_line_match_maps_split_entity_to_union_box() -> None:
    # match_entities_to_ocr no longer reconstructs visual lines internally;
    # callers join split blocks first via reconstruct_visual_line_blocks.
    blocks = [
        OCRTextBlock(
            text="海南",
            polygon=[[100, 40], [140, 40], [140, 70], [100, 70]],
            confidence=0.98,
        ),
        OCRTextBlock(
            text="工程服务有限公司",
            polygon=[[175, 38], [320, 38], [320, 70], [175, 70]],
            confidence=0.98,
        ),
    ]

    regions = match_entities_to_ocr(
        reconstruct_visual_line_blocks(blocks),
        [{"type": "COMPANY_NAME", "text": "海南工程服务有限公司"}],
    )

    assert len(regions) == 1
    assert regions[0].source == "text_match"
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (100, 38, 220, 32)


def test_compact_form_row_match_covers_whole_block() -> None:
    # Without aligned per-character boxes there is no sub-span estimation any
    # more: a matched entity masks the whole OCR block (safe over precise).
    block = OCRTextBlock(
        text=(
            "\u79d1\u522b\uff1a\u5916\u79d1\u5e8a\u53f7\uff1a9"
            "\u59d3\u540d\uff1a\u5f20\u4e09"
            "\u6027\u522b\uff1a\u7537\u5e74\u9f84\uff1a61"
        ),
        polygon=[[100, 100], [1000, 100], [1000, 160], [100, 160]],
        confidence=0.98,
    )

    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": "\u5f20\u4e09"}])

    assert len(regions) == 1
    assert regions[0].source == "text_match"
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (100, 100, 900, 60)


def test_overlapping_whole_block_regions_dedupe_to_one() -> None:
    # Two PERSON values matched in the same block produce identical whole-block
    # boxes; the pure-IoU dedupe keeps exactly one region (coverage unchanged).
    block = OCRTextBlock(
        text=(
            "\u79d1\u522b\uff1a\u666e\u5916 \u75c5\u533a\uff1a\u6b63 "
            "\u5e8a\u53f7\uff1a8.2 \u59d3\u540d\uff1a\u5173\u6c38\u5a1f "
            "\u6027\u522b\uff1a\u7537 \u5e74\u9f84\uff1a68"
        ),
        polygon=[[590, 340], [1372, 340], [1372, 400], [590, 400]],
        confidence=0.98,
    )

    regions = match_entities_to_ocr(
        [block],
        [
            {"type": "PERSON", "text": "\u5173\u6c38"},
            {"type": "PERSON", "text": "\u5173\u6c38\u5a1f"},
        ],
    )

    assert len(regions) == 1
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (590, 340, 782, 60)
    assert _dedupe_ocr_regions(regions) == regions


def test_merged_supplement_block_keeps_full_name_coverage() -> None:
    # A coarse structure-service block must not displace the VL block that
    # carries the full name; the full-name pixels stay covered after merge.
    vl_block = OCRTextBlock(
        text=(
            "\u79d1\u522b\uff1a\u666e\u5916 \u75c5\u533a\uff1a\u6b63 "
            "\u5e8a\u53f7\uff1a8.2 \u59d3\u540d\uff1a\u5173\u6c38\u5a1f "
            "\u6027\u522b\uff1a\u7537 \u5e74\u9f84\uff1a68"
        ),
        polygon=[[590, 340], [1372, 340], [1372, 400], [590, 400]],
        confidence=0.98,
    )
    structure_block = OCRTextBlock(
        text="\u5e8a\u53f7\uff1a9\u59d3\u540d\uff1a\u5173\u6c38\u6027\u522b\uff1a\u7537\u5e74\u660e\uff1a",
        polygon=[[930, 340], [1240, 340], [1240, 400], [930, 400]],
        confidence=0.95,
    )

    merged_blocks = _merge_ocr_blocks([vl_block], [structure_block])
    regions = match_entities_to_ocr(
        merged_blocks,
        [
            {"type": "PERSON", "text": "\u5173\u6c38"},
            {"type": "PERSON", "text": "\u5173\u6c38\u5a1f"},
        ],
    )

    assert any(
        region.left <= 590 and region.left + region.width >= 1372 for region in regions
    )


def test_compressed_multiline_ocr_block_keeps_full_line_height() -> None:
    block = OCRTextBlock(
        text=(
            "\u4e00\u3001\u81ea\u7136\u9879\u76ee\uff1a\u59d3\u540d\uff1a\u5f20\u4e09  \n"
            "\u6027\u522b\uff1a\u7537  \n"
            "\u5e74\u9f84\uff1a61\u5c81  \n"
            "\u8fc7\u654f\u836f\u7269\uff1a\u65e0"
        ),
        polygon=[[123, 491], [478, 491], [478, 537], [123, 537]],
        confidence=0.98,
    )

    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": "\u5f20\u4e09"}])

    assert len(regions) == 1
    assert regions[0].height >= 40
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (123, 491, 355, 46)


def _flat_block(text: str, left: int, top: int, width: int, height: int) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        polygon=[[left, top], [left + width, top], [left + width, top + height], [left, top + height]],
        confidence=0.9,
    )


def test_amount_format_text_is_a_pure_format_judgement() -> None:
    assert _is_amount_format_text("715700")
    assert _is_amount_format_text("715,700.00")
    assert _is_amount_format_text("￥1,431,400")
    assert _is_amount_format_text("2")

    assert not _is_amount_format_text("1684000元")  # unit suffix = running text
    assert not _is_amount_format_text("SZAI-300")
    assert not _is_amount_format_text("40%")
    assert not _is_amount_format_text("")


def test_positionless_whole_block_claim_yields_to_dedicated_box() -> None:
    # A signature name matched inside a chars-less VL paragraph produces an
    # uncropped whole-block region (label + handwriting + the next line); the
    # same name also matched its own handwriting block. The dedicated box is
    # the occurrence — the positionless containment claim is dropped, even
    # though the handwriting box pokes a few pixels outside the paragraph
    # (strict containment never fires on real detector output).
    paragraph = OCRTextBlock(
        text="法定代表人/授权代表（签字）：张伟\n日期：2024年05月28日",
        polygon=[[38, 1361], [429, 1361], [429, 1400], [38, 1400]],
    )
    handwriting = OCRTextBlock(
        text="张伟",
        polygon=[[311, 1350], [430, 1350], [430, 1418], [311, 1418]],
    )

    regions = match_entities_to_ocr(
        [paragraph, handwriting], [{"type": "PERSON", "text": "张伟"}]
    )

    assert [(r.left, r.width) for r in regions] == [(311, 119)]


def test_positionless_claim_yields_to_cropped_region_too() -> None:
    # The date inside the chars-less VL paragraph (签字 line + 日期 line merged)
    # produces a two-line whole-block region; the same date matched its own
    # structure line and was value-cropped there. A cropped hit is position
    # evidence just like a dedicated block — the paragraph claim is redundant.
    paragraph = OCRTextBlock(
        text="法定代表人/授权代表（签字）：张伟\n日期：2024年05月28日",
        polygon=[[38, 1361], [429, 1361], [429, 1400], [38, 1400]],
    )
    date_line = OCRTextBlock(
        text="日期：2024年05月28日",
        polygon=[[90, 1395], [290, 1395], [290, 1418], [90, 1418]],
        chars=[
            {"c": g, "x1": 90 + i * 14, "y1": 1395, "x2": 104 + i * 14, "y2": 1418}
            for i, g in enumerate("日期：2024年05月28日")
        ],
    )

    regions = match_entities_to_ocr(
        [paragraph, date_line], [{"type": "DATE", "text": "2024年05月28日"}]
    )

    assert len(regions) == 1
    assert regions[0].left == 132  # cropped to the value inside the date line


def test_whole_block_claim_stays_without_dedicated_box() -> None:
    # When the containment claim is the only coverage (no dedicated box, or a
    # dedicated box elsewhere on the page), it must stay — dropping it would
    # be a missed redaction.
    paragraph = OCRTextBlock(
        text="法定代表人/授权代表（签字）：张伟",
        polygon=[[38, 1361], [429, 1361], [429, 1400], [38, 1400]],
    )
    far_away_dedicated = OCRTextBlock(
        text="张伟",
        polygon=[[100, 200], [220, 200], [220, 240], [100, 240]],
    )

    regions = match_entities_to_ocr(
        [paragraph, far_away_dedicated], [{"type": "PERSON", "text": "张伟"}]
    )

    lefts = sorted(r.left for r in regions)
    assert lefts == [38, 100]  # both occurrences stay covered


def test_nested_same_entity_regions_keep_tightest_box() -> None:
    # Mixed-granularity OCR (PP-Structure line + coarse VL layout paragraph)
    # matches the same value at both granularities; whole-block coverage then
    # yields nested regions for one physical instance. The outer paragraph-
    # sized region is redundant evidence of the same value and is dropped; the
    # tight line box keeps the entity pixels covered.
    line = _flat_block("联系人：沈样涛", 280, 312, 280, 42)
    paragraph = _flat_block("甲方信息\n联系人：沈样涛\n电话：13451775049", 228, 254, 1546, 150)

    regions = match_entities_to_ocr(
        [line, paragraph],
        [{"type": "PERSON", "text": "沈样涛"}],
    )

    assert len(regions) == 1
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (280, 312, 280, 42)


def test_nested_amount_regions_dedupe_by_value_signature() -> None:
    # The two OCR engines can read the same amount span with divergent
    # punctuation (structure: ￥1431400，00元 / VL paragraph: ￥1431400.00元).
    # Value identity for AMOUNT uses the existing _amount_value_signature, so
    # the nested paragraph-sized region is still recognized as redundant outer
    # evidence of the same value.
    regions = _dedupe_ocr_regions([
        SensitiveRegion(
            text="￥1431400.00元，",
            entity_type="AMOUNT",
            left=228, top=1254, width=1546, height=150,
            confidence=1.0,
            source="text_match",
        ),
        SensitiveRegion(
            text="￥1431400，00元，",
            entity_type="AMOUNT",
            left=230, top=1340, width=302, height=38,
            confidence=1.0,
            source="text_match",
        ),
    ])

    assert len(regions) == 1
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (230, 1340, 302, 38)


def test_nested_different_amounts_keep_both_regions() -> None:
    # A paragraph region matched for one value must NOT be dropped because a
    # different value's tight region nests inside it (coverage would be lost).
    regions = _dedupe_ocr_regions([
        SensitiveRegion(
            text="￥1684000.00元",
            entity_type="AMOUNT",
            left=228, top=1254, width=1546, height=150,
            confidence=1.0,
            source="text_match",
        ),
        SensitiveRegion(
            text="￥1431400.00元",
            entity_type="AMOUNT",
            left=230, top=1340, width=302, height=38,
            confidence=1.0,
            source="text_match",
        ),
    ])

    assert len(regions) == 2


def test_same_entity_in_disjoint_blocks_keeps_both_regions() -> None:
    # Containment-based suppression must not touch the deliberate behavior of
    # keeping one region per physical occurrence (e.g. a name in the 姓名 cell
    # and again in a signature line).
    blocks = [
        _flat_block("姓名：张三", 100, 100, 200, 30),
        _flat_block("签字：张三", 100, 700, 200, 30),
    ]

    regions = match_entities_to_ocr(blocks, [{"type": "PERSON", "text": "张三"}])

    assert len(regions) == 2


class _StubOcrService:
    """OCR client stub: PP-StructureV3 fragments + a VL full-page pass."""

    base_url = "stub://ocr-vl-supplement"

    def __init__(self, structure_items: list[OCRItem], vl_items: list[OCRItem]) -> None:
        self._structure_items = structure_items
        self._vl_items = vl_items
        self.vl_calls = 0

    def is_available(self) -> bool:
        return True

    def extract_structure_boxes(self, image_bytes: bytes) -> list[OCRItem]:
        return self._structure_items

    def extract_text_boxes(self, image_bytes: bytes) -> list[OCRItem]:
        self.vl_calls += 1
        return self._vl_items


def _ocr_item(text: str, x: float, y: float, width: float, height: float) -> OCRItem:
    return OCRItem(text=text, x=x, y=y, width=width, height=height, confidence=0.95)


def _seal_fragment_fixture() -> tuple[list[OCRItem], list[OCRItem]]:
    # 信创合同 p5: the red seal crushes 纳达信息服务有限 so structure only sees
    # the two fragments; the VL full-page pass reads the whole line.
    structure_items = [
        _ocr_item("甲方（盖章）：苏州市", 0.05, 0.50, 0.40, 0.05),
        _ocr_item("公司", 0.85, 0.50, 0.10, 0.05),
    ]
    vl_items = [
        _ocr_item("甲方（盖章）：苏州市纳达信息服务有限公司", 0.05, 0.50, 0.90, 0.05),
    ]
    return structure_items, vl_items


def test_structure_primary_merges_vl_supplement_blocks(monkeypatch) -> None:
    # Structure stays the primary block set; the VL block that carries the
    # seal-crushed full company name is merged in as a supplement through the
    # existing whole-block IoU contract.
    monkeypatch.setattr(settings, "OCR_VL_ENABLED", True)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL", True)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_MIN_BOXES", 1)
    structure_items, vl_items = _seal_fragment_fixture()
    service = _StubOcrService(structure_items, vl_items)

    blocks, visual_regions = run_paddle_ocr(
        Image.new("RGB", (500, 400), "white"),
        service,
        selected_entity_types=["PERSON"],
    )

    assert service.vl_calls == 1
    texts = [block.text for block in blocks]
    assert texts[:2] == ["甲方（盖章）：苏州市", "公司"]  # structure blocks first
    assert "甲方（盖章）：苏州市纳达信息服务有限公司" in texts
    assert visual_regions == []


def test_vl_disabled_keeps_structure_only_path(monkeypatch) -> None:
    # OCR_VL_ENABLED=0 must reproduce today's behavior exactly: structure-only
    # result and no /ocr (VL) call even with the supplement flag on.
    monkeypatch.setattr(settings, "OCR_VL_ENABLED", False)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL", True)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_MIN_BOXES", 1)
    structure_items, vl_items = _seal_fragment_fixture()
    service = _StubOcrService(structure_items, vl_items)

    blocks, _ = run_paddle_ocr(
        Image.new("RGB", (500, 401), "white"),
        service,
        selected_entity_types=["PERSON"],
    )

    assert service.vl_calls == 0
    assert [block.text for block in blocks] == ["甲方（盖章）：苏州市", "公司"]


def test_vl_supplement_drops_duplicate_vl_blocks(monkeypatch) -> None:
    # A VL block that re-reads an existing structure line (same text, same box)
    # is deduplicated by the existing merge contract instead of doubling up.
    monkeypatch.setattr(settings, "OCR_VL_ENABLED", True)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL", True)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_MIN_BOXES", 1)
    structure_items, vl_items = _seal_fragment_fixture()
    vl_items = [*vl_items, _ocr_item("公司", 0.85, 0.50, 0.10, 0.05)]
    service = _StubOcrService(structure_items, vl_items)

    blocks, _ = run_paddle_ocr(
        Image.new("RGB", (500, 402), "white"),
        service,
        selected_entity_types=["PERSON"],
    )

    assert [block.text for block in blocks].count("公司") == 1


def test_clone_text_block_preserves_char_boxes() -> None:
    # The OCR output cache round-trips blocks through _clone_text_block.
    # Dropping chars there silently disables value-level cropping on every
    # cache hit: the first detection masks the value only, the next one masks
    # the whole line (label included) because the cloned block lost the char
    # boxes that prove where the value sits.
    block = OCRTextBlock(
        text="户名：上海淞江",
        polygon=[[0.0, 0.0], [100.0, 0.0], [100.0, 20.0], [0.0, 20.0]],
        confidence=0.97,
        chars=[
            {"c": "户", "x1": 0, "y1": 0, "x2": 12, "y2": 20},
            {"c": "名", "x1": 12, "y1": 0, "x2": 24, "y2": 20},
        ],
    )
    clone = _clone_text_block(block)
    assert clone.chars == block.chars
    assert clone.chars is not block.chars  # cached copy must not share state


def test_merge_drops_vl_reread_of_same_line() -> None:
    # The VL pass re-reads an existing structure line with one divergent glyph
    # (戬/我) or a dropped glyph, plus a slightly wobbled box. Same place with
    # equal glyph count, or reading a subset of the glyphs, is the same
    # physical line — not new content. Keeping both feeds HaS two variants of
    # one value, and the whole-line VL box (no char boxes) later displaces the
    # value-cropped structure box.
    structure_block = OCRTextBlock(
        text="开户行：农行上海我浜支行",
        polygon=[[82, 228], [288, 228], [288, 250], [82, 250]],
    )
    equal_count_reread = OCRTextBlock(
        text="开户行：农行上海戬浜支行",
        polygon=[[82, 231], [290, 231], [290, 251], [82, 251]],
    )
    dropped_glyph_reread = OCRTextBlock(
        text="开户行：农行上海浜支行",
        polygon=[[82, 231], [290, 231], [290, 251], [82, 251]],
    )

    merged = _merge_ocr_blocks(
        [structure_block], [equal_count_reread, dropped_glyph_reread]
    )

    assert [block.text for block in merged] == ["开户行：农行上海我浜支行"]


def test_merge_keeps_vl_block_reading_more_content() -> None:
    # A VL block whose text is a superset of the overlapping structure block
    # (the seal-crushed full company name) is new evidence, not a re-read.
    structure_block = OCRTextBlock(
        text="甲方（盖章）：苏州市",
        polygon=[[50, 200], [250, 200], [250, 220], [50, 220]],
    )
    vl_block = OCRTextBlock(
        text="甲方（盖章）：苏州市纳达信息服务有限公司",
        polygon=[[50, 200], [420, 200], [420, 220], [50, 220]],
    )

    merged = _merge_ocr_blocks([structure_block], [vl_block])

    assert "甲方（盖章）：苏州市纳达信息服务有限公司" in [b.text for b in merged]


def test_merge_adopts_more_accurate_extra_reading_on_same_line() -> None:
    # VL recognises glyphs more accurately than the PP-OCR line recognizer
    # (戬浜 vs 我浜). With prefer_extra_text, an equal-glyph-count re-read of
    # the same line carries its text onto the structure block while the
    # structure geometry and char boxes (value-crop evidence) are kept.
    structure_block = OCRTextBlock(
        text="开户行：农行上海我浜支行",
        polygon=[[82, 228], [288, 228], [288, 250], [82, 250]],
        chars=[
            {"c": g, "x1": 82 + i * 19, "y1": 228, "x2": 101 + i * 19, "y2": 250}
            for i, g in enumerate("开户行：农行上海浜支行")
        ],
    )
    vl_block = OCRTextBlock(
        text="开户行：农行上海戬浜支行",
        polygon=[[82, 231], [290, 231], [290, 251], [82, 251]],
    )

    merged = _merge_ocr_blocks([structure_block], [vl_block], prefer_extra_text=True)

    assert len(merged) == 1
    assert merged[0].text == "开户行：农行上海戬浜支行"  # VL reading wins
    assert len(merged[0].chars) == 11  # structure char boxes kept
    assert merged[0].bbox == (82, 228, 290, 251)  # union, never under-covers


def test_merge_adopts_fuller_extra_reading_of_same_pixels() -> None:
    # VL recovers a glyph the line recognizer dropped inside the same box
    # (减震器 vs 减器 under the seal). The fuller reading is carried on the
    # structure block with the union box; it is not a second block that would
    # later displace the value-cropped one.
    structure_block = OCRTextBlock(
        text="户名：上海淞江减器集团有限公司",
        polygon=[[82, 195], [354, 195], [354, 218], [82, 218]],
    )
    vl_block = OCRTextBlock(
        text="户名：上海淞江减震器集团有限公司",
        polygon=[[80, 196], [360, 196], [360, 219], [80, 219]],
    )

    merged = _merge_ocr_blocks([structure_block], [vl_block], prefer_extra_text=True)

    assert len(merged) == 1
    assert merged[0].text == "户名：上海淞江减震器集团有限公司"
    assert merged[0].bbox == (80, 195, 360, 219)  # union of both boxes


def test_value_crop_survives_equal_length_char_divergence() -> None:
    # 帐号 line: the line recognizer reads 帐, the char recognizer reads 账 for
    # the same glyph. Glyph counts are equal, so positions correspond 1:1 and
    # the digits' own token box is trustworthy — the account number crops to
    # its digits instead of masking the 帐号： label as a full line.
    block = OCRTextBlock(
        text="帐号： 03832700040031040",
        polygon=[[100, 0], [400, 0], [400, 20], [100, 20]],
        chars=[
            {"c": "账", "x1": 100, "y1": 0, "x2": 120, "y2": 20},
            {"c": "号", "x1": 120, "y1": 0, "x2": 140, "y2": 20},
            {"c": "：", "x1": 140, "y1": 0, "x2": 150, "y2": 20},
            {"c": "03832700040031040", "x1": 150, "y1": 0, "x2": 400, "y2": 20},
        ],
    )

    regions = match_entities_to_ocr(
        [block], [{"type": "BANK_CARD", "text": "03832700040031040"}]
    )

    assert len(regions) == 1
    assert (regions[0].left, regions[0].width) == (150, 250)
    assert (regions[0].top, regions[0].height) == (0, 20)  # full line height kept


def test_value_crop_covers_span_with_interior_char_gap() -> None:
    # 开户行 line: the char list drops one interior glyph (我). The span's
    # first and last glyphs still have corresponding boxes and char boxes run
    # left-to-right, so their union covers the gap — the bank name crops while
    # the 开户行： label stays out.
    glyphs = ["开", "户", "行", "：", "农", "行", "上", "海", "我", "浜", "支", "行"]
    chars = [
        {"c": g, "x1": 100 + i * 20, "y1": 0, "x2": 120 + i * 20, "y2": 20}
        for i, g in enumerate(glyphs)
        if g != "我"
    ]
    block = OCRTextBlock(
        text="开户行：农行上海我浜支行",
        polygon=[[100, 0], [340, 0], [340, 20], [100, 20]],
        chars=chars,
    )

    regions = match_entities_to_ocr(
        [block], [{"type": "BANK_NAME", "text": "农行上海我浜支行"}]
    )

    assert len(regions) == 1
    assert (regions[0].left, regions[0].width) == (180, 160)  # 农(180) .. 行(340)


def test_value_crop_recovers_missing_span_edge_from_neighbour() -> None:
    # The service sometimes drops a leading char box (chars 9000... under text
    # 89000...). The span's first glyph 8 has no box, so a union of the remaining
    # boxes (175..) would leave it readable. The neighbour just outside the span
    # — the colon ending at x=150 — bounds the entity's left edge, so the crop
    # starts at 150 and covers the unboxed 8 (150..175) without masking the
    # whole block (the 帐号 label at 100..150 stays out).
    block = OCRTextBlock(
        text="帐号：89000123456",
        polygon=[[100, 0], [400, 0], [400, 20], [100, 20]],
        chars=[
            {"c": "帐", "x1": 100, "y1": 0, "x2": 120, "y2": 20},
            {"c": "号", "x1": 120, "y1": 0, "x2": 140, "y2": 20},
            {"c": "：", "x1": 140, "y1": 0, "x2": 150, "y2": 20},
            {"c": "9000123456", "x1": 175, "y1": 0, "x2": 400, "y2": 20},
        ],
    )

    regions = match_entities_to_ocr(
        [block], [{"type": "BANK_CARD", "text": "89000123456"}]
    )

    assert len(regions) == 1
    assert (regions[0].left, regions[0].width) == (150, 250)  # colon edge .. block end


def test_visual_region_fallback_keeps_structure_blocks_primary(monkeypatch) -> None:
    # Selection includes a visual-only type but structure returned no visual
    # regions, so VL must still run for them. The text-block set stays
    # structure-primary even with the supplement flag off: handing VL the
    # primary slot let its generative whole-line blocks (no char boxes)
    # displace the per-line structure blocks, masking label and value as one
    # full line (户名/开户行/帐号 regression).
    monkeypatch.setattr(settings, "OCR_VL_ENABLED", True)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL", False)
    monkeypatch.setattr(settings, "OCR_STRUCTURE_PRIMARY_MIN_BOXES", 1)
    structure_items, vl_items = _seal_fragment_fixture()
    service = _StubOcrService(structure_items, vl_items)

    blocks, _ = run_paddle_ocr(
        Image.new("RGB", (500, 403), "white"),
        service,
        selected_entity_types=["PERSON", "SEAL"],
    )

    assert service.vl_calls == 1
    texts = [block.text for block in blocks]
    assert texts[:2] == ["甲方（盖章）：苏州市", "公司"]  # structure blocks first
    assert "甲方（盖章）：苏州市纳达信息服务有限公司" in texts


def test_amount_queries_both_numeral_systems() -> None:
    # The 0.6B NER deduplicates same-value mentions inside one bucket, so on a
    # full page it returns ¥1,294,000.00 and silently drops 壹佰贰拾玖万肆仟元整.
    # Separate buckets have no shared value to deduplicate: when AMOUNT is in
    # the schema, the prompt also asks for 大写金额 (open-vocabulary type), and
    # the answer key maps back to AMOUNT.
    from app.models.type_mapping import cn_to_id, has_query_labels_for

    assert has_query_labels_for("AMOUNT") == ["金额", "大写金额"]
    assert cn_to_id("大写金额") == "AMOUNT"
    # Other types keep their single own label.
    assert has_query_labels_for("PERSON") == ["姓名"]


def test_uppercase_amount_entity_crops_to_its_glyphs() -> None:
    # An AMOUNT value matched inside the 合计 line must crop to the uppercase
    # run itself, not mask the whole line.
    text = "合计（人民币）：壹佰贰拾玖万肆仟元整（¥1,294,000.00）"
    chars = [
        {"c": g, "x1": 100 + i * 20, "y1": 0, "x2": 120 + i * 20, "y2": 20}
        for i, g in enumerate(text)
    ]
    block = OCRTextBlock(
        text=text,
        polygon=[[100, 0], [100 + len(text) * 20, 0], [100 + len(text) * 20, 20], [100, 20]],
        chars=chars,
    )

    regions = match_entities_to_ocr(
        [block], [{"type": "AMOUNT", "text": "壹佰贰拾玖万肆仟元整"}]
    )

    amount_regions = [r for r in regions if r.text == "壹佰贰拾玖万肆仟元整"]
    assert len(amount_regions) == 1
    # 壹 is the 9th glyph (index 8): crop starts at 100 + 8*20 = 260.
    assert (amount_regions[0].left, amount_regions[0].width) == (260, 200)


def test_cross_line_split_grows_collapsed_char_band_to_row_height() -> None:
    # On a tilted phone photo the word engine flattens each line's char boxes to
    # a near-zero y-band while the line BLOCK keeps its real height. A cross-line
    # value split per line must take each line's structural row height, not the
    # collapsed char band, or the crop is a readable sliver.
    from app.services.vision.ocr_entity_match import split_regions_across_lines

    def line_block(text: str, top: int, band_y: int) -> OCRTextBlock:
        # real block height 30px; chars collapsed to a 2px band at band_y
        return OCRTextBlock(
            text=text,
            polygon=[[100, top], [400, top], [400, top + 30], [100, top + 30]],
            confidence=0.95,
            chars=[
                {"c": c, "x1": 100 + i * 30, "y1": band_y, "x2": 128 + i * 30, "y2": band_y + 2}
                for i, c in enumerate(text)
            ],
        )

    b1 = line_block("门诊三楼", 100, 114)
    b2 = line_block("北走廊东侧", 140, 154)
    region = SensitiveRegion(
        text="门诊三楼北走廊东侧", entity_type="ADDRESS",
        left=100, top=100, width=300, height=70, confidence=1.0, source="text_match",
    )

    out = split_regions_across_lines([region], [b1, b2])

    assert len(out) == 2  # split into the two lines
    for r in out:
        # grown to ~row height (30), NOT the 2px collapsed char band
        assert r.height >= 20, f"sliver crop leaks glyphs: height={r.height}"
