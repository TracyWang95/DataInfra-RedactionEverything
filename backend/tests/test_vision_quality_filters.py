from PIL import Image, ImageDraw

from app.core.config import settings
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion
from app.services.ocr_service import OCRItem
from app.services.vision.ocr_pipeline import (
    _dedupe_ocr_regions,
    _is_amount_format_text,
    _is_amount_header_label,
    _merge_ocr_blocks,
    expand_table_blocks,
    match_entities_to_ocr,
    recall_table_amount_entities,
    reconstruct_visual_line_blocks,
    run_paddle_ocr,
)
from app.services.vision_service import VisionService


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


def test_compact_ocr_padding_is_geometry_capped() -> None:
    left, _top, width, _height = VisionService._expand_ocr_region(
        left=500,
        top=100,
        region_width=80,
        region_height=30,
        page_width=2000,
        page_height=3000,
        entity_type="PERSON",
    )

    assert left >= 490
    assert width <= 100


_CONTRACT_TABLE_HTML = (
    "<table>"
    "<tr><td>序号</td><td>设备名称</td><td>数量</td><td>单价（元）</td><td>合价(元）</td></tr>"
    "<tr><td>1</td><td>一体机</td><td>2</td><td>715700</td><td>1431400</td></tr>"
    "<tr><td>2</td><td>集成服务</td><td>1</td><td>252600</td><td>252600</td></tr>"
    '<tr><td colspan="5">总计：1684000元</td></tr>'
    "</table>"
)


def _table_block() -> OCRTextBlock:
    return OCRTextBlock(
        text=_CONTRACT_TABLE_HTML,
        polygon=[[100, 100], [900, 100], [900, 500], [100, 500]],
        confidence=0.95,
    )


def _flat_block(text: str, left: int, top: int, width: int, height: int) -> OCRTextBlock:
    return OCRTextBlock(
        text=text,
        polygon=[[left, top], [left + width, top], [left + width, top + height], [left, top + height]],
        confidence=0.9,
    )


def test_table_html_amount_recall_uses_column_index_semantics() -> None:
    # Header labels 单价（元）/合价(元） mark their HTML columns as amount
    # columns; numeric cells in those columns are recalled. Numeric cells in
    # other columns (序号 1/2, 数量 2/1) and non-numeric cells (总计 row with
    # 元 suffix) are not. Identical values (252600 twice) collapse to one
    # entity; the matcher re-expands a value to every containing cell.
    entities = recall_table_amount_entities(expand_table_blocks([_table_block()]))

    assert [entity["text"] for entity in entities] == ["715700", "1431400", "252600"]
    assert all(entity["type"] == "AMOUNT" for entity in entities)
    assert all(entity["source"] == "table_semantic" for entity in entities)


def test_table_html_amount_recall_works_on_raw_table_block() -> None:
    # The same recall works when the <table> block was not expanded upstream.
    entities = recall_table_amount_entities([_table_block()])

    assert [entity["text"] for entity in entities] == ["715700", "1431400", "252600"]


def test_table_without_amount_header_recalls_nothing() -> None:
    html = (
        "<table>"
        "<tr><td>序号</td><td>名称</td><td>数量</td></tr>"
        "<tr><td>1</td><td>一体机</td><td>715700</td></tr>"
        "</table>"
    )
    block = OCRTextBlock(
        text=html,
        polygon=[[100, 100], [900, 100], [900, 300], [100, 300]],
        confidence=0.95,
    )

    assert recall_table_amount_entities(expand_table_blocks([block])) == []


def test_flat_table_layout_amount_recall_by_header_box_span() -> None:
    # PP-StructureV3 returns this contract table as independent cell boxes
    # without <table> markup (信创合同 p6). The header cell box itself defines
    # the column: numeric blocks centered inside the header span and below it
    # are recalled; numeric blocks in other columns (数量 2/1), above the
    # header, or with non-numeric decoration (总计：1684000元) are not.
    blocks = [
        _flat_block("99", 790, 100, 20, 20),  # numeric but above the header
        _flat_block("序号", 136, 177, 32, 28),
        _flat_block("数量", 710, 177, 32, 28),
        _flat_block("单价(元）", 764, 177, 62, 27),
        _flat_block("合价（元）", 848, 178, 60, 25),
        _flat_block("2", 720, 294, 13, 21),
        _flat_block("715700", 777, 294, 43, 23),
        _flat_block("1431400", 856, 294, 48, 22),
        _flat_block("1", 720, 423, 11, 20),
        _flat_block("252600", 777, 422, 42, 23),
        _flat_block("252600", 859, 422, 42, 23),
        _flat_block("总计：1684000元", 480, 489, 98, 22),
    ]

    entities = recall_table_amount_entities(blocks)

    assert [entity["text"] for entity in entities] == ["715700", "1431400", "252600"]
    assert all(entity["source"] == "table_semantic" for entity in entities)


def test_recalled_amounts_match_back_to_whole_cell_blocks() -> None:
    # The recalled value is matched back like any entity: whole matched block,
    # IoU-only dedupe. A value appearing in two cells keeps both regions.
    blocks = [
        _flat_block("单价(元）", 764, 177, 62, 27),
        _flat_block("合价（元）", 848, 178, 60, 25),
        _flat_block("252600", 777, 422, 42, 23),
        _flat_block("252600", 859, 422, 42, 23),
    ]

    regions = match_entities_to_ocr(blocks, recall_table_amount_entities(blocks))

    assert len(regions) == 2
    assert all(region.entity_type == "AMOUNT" for region in regions)
    assert all(region.source == "table_semantic" for region in regions)
    assert {(region.left, region.top, region.width, region.height) for region in regions} == {
        (777, 422, 42, 23),
        (859, 422, 42, 23),
    }


def test_amount_format_text_is_a_pure_format_judgement() -> None:
    assert _is_amount_format_text("715700")
    assert _is_amount_format_text("715,700.00")
    assert _is_amount_format_text("￥1,431,400")
    assert _is_amount_format_text("2")

    assert not _is_amount_format_text("1684000元")  # unit suffix = running text
    assert not _is_amount_format_text("SZAI-300")
    assert not _is_amount_format_text("40%")
    assert not _is_amount_format_text("")


def test_amount_header_label_is_identity_not_containment() -> None:
    assert _is_amount_header_label("单价（元）")
    assert _is_amount_header_label("单价(元）")  # mixed-width OCR parentheses
    assert _is_amount_header_label("金额")
    assert _is_amount_header_label("费用(万元)")

    assert not _is_amount_header_label("总计：1684000元")
    assert not _is_amount_header_label("合同金额")  # contains 金额 but is not a header label
    assert not _is_amount_header_label("设备名称")


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


def test_ocr_ink_refinement_ignores_long_form_line() -> None:
    image = Image.new("RGB", (220, 90), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(0, 45), (219, 45)], fill="black", width=2)
    draw.line([(88, 25), (88, 62)], fill="black", width=4)
    draw.line([(105, 25), (132, 62)], fill="black", width=4)
    draw.line([(150, 25), (150, 62)], fill="black", width=4)

    left, top, width, height = VisionService._refine_ocr_region_to_ink(image, 0, 0, 220, 90)

    assert left > 70
    assert top >= 20
    assert width < 90
    assert height < 50

