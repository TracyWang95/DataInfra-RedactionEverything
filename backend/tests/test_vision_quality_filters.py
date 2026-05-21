from app.models.schemas import BoundingBox
from app.services.hybrid_vision_service import OCRTextBlock
from app.services.vision.ocr_pipeline import match_entities_to_ocr, reconstruct_visual_line_blocks
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
            source="has_image",
            source_detail="has_image",
            evidence_source="has_image_model",
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
            source="has_image",
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
        source="has_image",
        source_detail="has_image",
        evidence_source="has_image_model",
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
        source="has_image",
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
        source="has_image",
        source_detail="local_red_seal_fallback",
        evidence_source="local_fallback",
    )

    assert service._filter_visual_artifacts([edge_seal]) == [edge_seal]
