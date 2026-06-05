from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.models.schemas import BoundingBox
from app.services.ocr_has_vision_service import OCRTextBlock
from app.services.vision.ocr_pipeline import (
    _augment_amount_entities_from_ocr,
    _dedupe_ocr_regions,
    _iter_probable_amount_tokens,
    _merge_ocr_blocks,
    match_entities_to_ocr,
    reconstruct_visual_line_blocks,
)
from app.services.vision.seal_detector import _has_dominant_dark_rule_line, detect_red_seal_regions
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
        blocks,
        [{"type": "COMPANY_NAME", "text": "海南工程服务有限公司"}],
    )

    assert len(regions) == 1
    assert regions[0].source == "visual_line_match"
    assert (regions[0].left, regions[0].top, regions[0].width, regions[0].height) == (100, 38, 220, 32)


def test_compact_form_row_match_shifts_to_field_value() -> None:
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
    assert regions[0].left > 520
    assert regions[0].width < 130


def test_compact_form_row_match_does_not_shift_into_next_field() -> None:
    block = OCRTextBlock(
        text=(
            "\u79d1\u522b\uff1a\u666e\u5916 \u75c5\u533a\uff1a\u6b63 "
            "\u5e8a\u53f7\uff1a8.2 \u59d3\u540d\uff1a\u5173\u6c38"
            "\u6027\u522b\uff1a\u7537 \u5e74\u9f84\uff1a68"
        ),
        polygon=[[590, 340], [1372, 340], [1372, 400], [590, 400]],
        confidence=0.98,
    )

    regions = match_entities_to_ocr([block], [{"type": "PERSON", "text": "\u5173\u6c38"}])

    assert len(regions) == 1
    assert regions[0].left < 1100
    assert regions[0].left + regions[0].width < 1160


def test_compact_form_vl_supplement_preserves_longer_person_value() -> None:
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

    assert any(region.text == "\u5173\u6c38\u5a1f" for region in regions)
    assert all(region.text != "\u5173\u6c38" for region in _dedupe_ocr_regions(regions))


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
    assert regions[0].left > 360
    assert regions[0].left + regions[0].width < 470


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


def test_table_semantic_amount_recall_uses_header_context() -> None:
    blocks = [
        OCRTextBlock(
            text="\u5355\u4ef7\uff08\u5143\uff09",
            polygon=[[600, 100], [700, 100], [700, 130], [600, 130]],
            confidence=0.99,
        ),
        OCRTextBlock(
            text="\u6570\u91cf\uff08\u53f0\uff09",
            polygon=[[730, 100], [810, 100], [810, 130], [730, 130]],
            confidence=0.99,
        ),
        OCRTextBlock(
            text="\u5408\u4ef7\uff08\u5143\uff09",
            polygon=[[840, 100], [940, 100], [940, 130], [840, 130]],
            confidence=0.99,
        ),
        OCRTextBlock(
            text="299,000.00",
            polygon=[[610, 180], [690, 180], [690, 210], [610, 210]],
            confidence=0.99,
        ),
        OCRTextBlock(
            text="2",
            polygon=[[765, 180], [775, 180], [775, 210], [765, 210]],
            confidence=0.99,
        ),
        OCRTextBlock(
            text="598,000.00",
            polygon=[[850, 180], [930, 180], [930, 210], [850, 210]],
            confidence=0.99,
        ),
        OCRTextBlock(
            text="\u5408\u8ba1\uff08\u4eba\u6c11\u5e01\uff09\uff1a\uff08\u00a51,294,000.00\uff09",
            polygon=[[520, 250], [940, 250], [940, 280], [520, 280]],
            confidence=0.99,
        ),
    ]

    entities = _augment_amount_entities_from_ocr([], blocks, ["AMOUNT"])
    texts = {entity["text"] for entity in entities}

    assert {"299,000.00", "598,000.00", "1,294,000.00"} <= texts
    assert all(entity.get("source") == "table_semantic" for entity in entities)


def test_amount_token_parser_supports_thousand_separators() -> None:
    assert _iter_probable_amount_tokens("299,000.00 / 598,000.00") == [
        "299,000.00",
        "598,000.00",
    ]


def test_visual_artifact_filter_removes_qr_adjacent_edge_seal_fallback() -> None:
    service = VisionService()
    boxes = [
        BoundingBox(
            id="qr",
            x=0.009,
            y=0.751,
            width=0.031,
            height=0.046,
            page=1,
            type="qr_code",
            text="二维码",
            source="visual_features",
            source_detail="locate_anything:detect",
            evidence_source="visual_feature_model",
        ),
        BoundingBox(
            id="edge_text",
            x=0.007,
            y=0.796,
            width=0.035,
            height=0.131,
            page=1,
            type="official_seal",
            text="公章",
            source="visual_features",
            source_detail="local_dark_seal_fallback",
            evidence_source="local_fallback",
        ),
    ]

    filtered = service._filter_visual_artifacts(boxes)

    assert [box.id for box in filtered] == ["qr"]


def test_visual_artifact_filter_keeps_model_backed_seal() -> None:
    service = VisionService()
    model_seal = BoundingBox(
        id="seal",
        x=0.326,
        y=0.111,
        width=0.163,
        height=0.218,
        page=1,
        type="official_seal",
        text="公章",
        confidence=0.96,
        source="visual_features",
        source_detail="locate_anything:detect",
        evidence_source="visual_feature_model",
    )

    assert service._filter_visual_artifacts([model_seal]) == [model_seal]


def test_visual_artifact_filter_keeps_isolated_red_bottom_arc_fallback() -> None:
    service = VisionService()
    bottom_arc = BoundingBox(
        id="bottom_arc",
        x=0.370,
        y=0.913,
        width=0.083,
        height=0.037,
        page=1,
        type="official_seal",
        text="公章",
        source="visual_features",
        source_detail="local_red_seal_fallback",
        evidence_source="local_fallback",
    )

    assert service._filter_visual_artifacts([bottom_arc]) == [bottom_arc]


def test_visual_artifact_filter_keeps_isolated_red_edge_seal_fallback() -> None:
    service = VisionService()
    edge_seal = BoundingBox(
        id="edge_seal",
        x=0.942,
        y=0.471,
        width=0.040,
        height=0.070,
        page=1,
        type="official_seal",
        text="公章",
        source="visual_features",
        source_detail="local_red_seal_fallback",
        evidence_source="local_fallback",
    )

    assert service._filter_visual_artifacts([edge_seal]) == [edge_seal]


def test_red_seal_fallback_skips_extreme_aspect_screenshot_pages() -> None:
    pytest.importorskip("cv2")
    img = Image.new("RGB", (1200, 280), "white")
    draw = ImageDraw.Draw(img)
    draw.ellipse((510, 60, 710, 240), outline=(220, 0, 0), width=10)

    assert detect_red_seal_regions(img) == []


def test_dark_seal_circle_filter_rejects_table_rule_line() -> None:
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    table_line_roi = np.full((120, 120), 255, dtype=np.uint8)
    table_line_roi[58:62, :] = 0

    round_stamp_roi = np.full((120, 120), 255, dtype=np.uint8)
    yy, xx = np.indices(round_stamp_roi.shape)
    radius = np.sqrt((xx - 60) ** 2 + (yy - 60) ** 2)
    round_stamp_roi[(radius >= 42) & (radius <= 48)] = 0

    assert _has_dominant_dark_rule_line(table_line_roi)
    assert not _has_dominant_dark_rule_line(round_stamp_roi)


def test_signature_anchor_priority_prefers_short_label_boxes() -> None:
    coarse = (
        "cached_ocr",
        1,
        SimpleNamespace(text="患者已知晓风险并表示理解签字麻醉医师", width=0.82, height=0.30),
    )
    label = (
        "cached_ocr",
        2,
        SimpleNamespace(text="麻醉医师", width=0.08, height=0.02),
    )

    assert sorted([coarse, label], key=VisionService._signature_anchor_priority)[0] == label


def test_signature_anchor_text_rejects_contract_prose() -> None:
    assert not VisionService._is_signature_anchor_text(
        "本合同一式两份，自双方签章后生效，传真件或扫描件具有同等法律效力。"
    )
    assert VisionService._is_signature_anchor_text("麻醉医师")
    assert VisionService._is_signature_anchor_text("签字")


def test_visual_artifact_filter_keeps_refined_signature_over_seal() -> None:
    service = VisionService()
    seal = BoundingBox(
        id="seal",
        x=0.55,
        y=0.76,
        width=0.20,
        height=0.15,
        page=1,
        type="official_seal",
        text="\u516c\u7ae0",
        confidence=0.95,
        source="visual_features",
        source_detail="locate_anything:detect",
        evidence_source="visual_feature_model",
    )
    signature = BoundingBox(
        id="signature",
        x=0.63,
        y=0.82,
        width=0.18,
        height=0.018,
        page=1,
        type="signature",
        text="\u7b7e\u5b57",
        confidence=0.86,
        source="visual_features",
        source_detail="signature#1:full:stroke_refined",
        evidence_source="visual_feature_model",
    )

    assert service._filter_visual_artifacts([seal, signature]) == [seal, signature]
