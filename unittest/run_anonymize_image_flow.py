#!/usr/bin/env python3
"""Run one-image anonymization flow aligned with stage modules (see $redaction-anonymize-image-flow)."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from PIL import Image, ImageOps

from app.models.redaction_schemas import RedactionConfig
from app.models.schemas import BoundingBox, FileType
from app.services import model_config_service
from app.services.ocr_has_vision_service import OCRTextBlock, SensitiveRegion, get_ocr_has_vision_service
from app.services.ocr_service import ocr_service
from app.services.pipeline_service import get_pipeline_types_for_mode
from app.services.redaction.image_redactor import prepare_image_redaction
from app.services.redaction_orchestrator import _default_pipeline_types
from app.services.vision.ocr_pipeline import match_entities_to_ocr, run_paddle_ocr
from app.services.vision_service import VisionService


def _json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_b64_png(path: Path, b64_text: str | None) -> None:
    if not b64_text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(b64_text))


def _block_dict(block: OCRTextBlock) -> dict:
    return {
        "text": block.text,
        "left": block.left,
        "top": block.top,
        "width": block.width,
        "height": block.height,
        "confidence": float(block.confidence),
        "char_box_count": len(block.chars or []),
    }


def _region_dict(region: SensitiveRegion) -> dict:
    return {
        "text": region.text,
        "entity_type": region.entity_type,
        "left": region.left,
        "top": region.top,
        "width": region.width,
        "height": region.height,
        "confidence": float(region.confidence),
        "source": region.source,
    }


def _bbox_dict(box: BoundingBox) -> dict:
    return box.model_dump()


def _ocr_item_dict(item) -> dict:
    return {
        "text": getattr(item, "text", ""),
        "x": float(getattr(item, "x", 0)),
        "y": float(getattr(item, "y", 0)),
        "width": float(getattr(item, "width", 0)),
        "height": float(getattr(item, "height", 0)),
        "confidence": float(getattr(item, "confidence", 0) or 0),
        "label": getattr(item, "label", "text"),
        "char_count": len(getattr(item, "chars", None) or []),
    }


async def run_flow(image_path: Path, output_dir: Path) -> None:
    started = time.perf_counter()
    image_bytes = image_path.read_bytes()
    image = ImageOps.exif_transpose(Image.open(image_path).convert("RGB"))
    width, height = image.size

    ocr_has_service = get_ocr_has_vision_service()
    ocr_client = ocr_has_service._ocr_service or ocr_service
    vision = VisionService()

    ocr_has_types = _default_pipeline_types(get_pipeline_types_for_mode("ocr_has"))
    visual_types = _default_pipeline_types(get_pipeline_types_for_mode("visual_features"))
    entity_type_ids = [t.id for t in ocr_has_types]
    stage_status: dict = {}

    summary: dict = {
        "input_image": str(image_path),
        "page_size": {"width": width, "height": height},
        "active_ocr": model_config_service.get_active_for_task(model_config_service.TASK_OCR).id
        if model_config_service.get_active_for_task(model_config_service.TASK_OCR)
        else None,
        "mineru_active": model_config_service.is_mineru_ocr_active(),
        "ocr_has_types": [t.id for t in ocr_has_types],
        "visual_feature_types": [t.id for t in visual_types],
    }

    # 1. OCR raw items
    raw_items = []
    if ocr_client and ocr_client.is_available():
        raw_items = ocr_client.extract_text_boxes(image_bytes)
    _json_dump(
        output_dir / "01_ocr_raw.json",
        {
            "count": len(raw_items),
            "full_text": "\n".join(item.text for item in raw_items if getattr(item, "text", "")),
            "items": [_ocr_item_dict(item) for item in raw_items],
        },
    )

    # 2. OCR blocks (normalized)
    ocr_blocks, ocr_visual_regions = run_paddle_ocr(
        image,
        ocr_client,
        require_visual_regions=bool(visual_types),
        selected_entity_types=entity_type_ids,
        stage_status=stage_status,
    )
    _json_dump(
        output_dir / "02_ocr_blocks.json",
        {
            "count": len(ocr_blocks),
            "ocr_visual_region_count": len(ocr_visual_regions),
            "stage_status": stage_status,
            "blocks": [_block_dict(block) for block in ocr_blocks],
            "ocr_visual_regions": [_region_dict(region) for region in ocr_visual_regions],
        },
    )

    # 3. Text NER
    entities: list[dict] = []
    if ocr_blocks:
        entities = await ocr_has_service._invoke_has_text_analysis(
            ocr_has_service._expand_table_blocks(ocr_blocks),
            ocr_has_types,
            stage_status,
        )
    _json_dump(
        output_dir / "03_entities.json",
        {
            "count": len(entities),
            "entities": entities,
        },
    )

    # 4. Entity -> box map (OCR path)
    matched_regions: list[SensitiveRegion] = list(ocr_visual_regions)
    if entities:
        matched_regions.extend(ocr_has_service._match_entities_to_ocr(ocr_blocks, entities))
    if ocr_blocks:
        matched_regions.extend(ocr_has_service._apply_regex_fallback(ocr_blocks, width, height))

    ocr_boxes = vision._filter_ocr_has_regions(image, matched_regions, page=1)
    for box in ocr_boxes:
        box.selected = True
    _json_dump(
        output_dir / "04_ocr_entity_boxes.json",
        {
            "matched_region_count": len(matched_regions),
            "bounding_box_count": len(ocr_boxes),
            "matched_regions": [_region_dict(region) for region in matched_regions],
            "bounding_boxes": [_bbox_dict(box) for box in ocr_boxes],
        },
    )
    _save_b64_png(output_dir / "04_ocr_entity_boxes.png", vision._draw_boxes_on_image(image, ocr_boxes))

    # 5. Visual detection
    visual_boxes: list[BoundingBox] = []
    if visual_types:
        visual_boxes, _ = await vision._detect_with_visual_features(
            image_bytes,
            page=1,
            pipeline_types=visual_types,
            draw_result=False,
        )
        for box in visual_boxes:
            box.selected = True
    _json_dump(
        output_dir / "05_visual_boxes.json",
        {
            "count": len(visual_boxes),
            "bounding_boxes": [_bbox_dict(box) for box in visual_boxes],
        },
    )
    _save_b64_png(output_dir / "05_visual_boxes.png", vision._draw_boxes_on_image(image, visual_boxes))

    # 6. Region merge / dedupe
    merged_boxes = vision._deduplicate_boxes([*ocr_boxes, *visual_boxes])
    merged_boxes = vision._expand_signature_boxes(merged_boxes)
    for box in merged_boxes:
        box.selected = True
    _json_dump(
        output_dir / "06_merged_boxes.json",
        {
            "input_count": len(ocr_boxes) + len(visual_boxes),
            "merged_count": len(merged_boxes),
            "bounding_boxes": [_bbox_dict(box) for box in merged_boxes],
        },
    )
    _save_b64_png(output_dir / "06_merged_boxes.png", vision._draw_boxes_on_image(image, merged_boxes))

    # 7. Mask plan
    config = RedactionConfig()
    selected_boxes, image_method, strength, fill_color = prepare_image_redaction(merged_boxes, config)
    mask_plan = {
        "selected_box_count": len(selected_boxes),
        "image_method": image_method,
        "strength": strength,
        "fill_color": fill_color,
        "replacement_mode": config.replacement_mode.value,
        "boxes": [_bbox_dict(box) for box in selected_boxes],
    }
    _json_dump(output_dir / "07_mask_plan.json", mask_plan)

    # 8. Preview image (apply mask plan directly; unittest path is outside upload dir)
    preview_image = image.copy()
    page_w, page_h = preview_image.size
    for bbox in selected_boxes:
        vision._apply_box_effect(
            preview_image,
            bbox,
            page_w,
            page_h,
            image_method,
            strength,
            fill_color,
        )
    preview_path = output_dir / "08_preview.png"
    preview_image.save(preview_path, format="PNG")

    summary.update(
        {
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "counts": {
                "ocr_raw_items": len(raw_items),
                "ocr_blocks": len(ocr_blocks),
                "entities": len(entities),
                "ocr_entity_boxes": len(ocr_boxes),
                "visual_boxes": len(visual_boxes),
                "merged_boxes": len(merged_boxes),
                "mask_boxes": len(selected_boxes),
            },
            "artifacts": [
                "01_ocr_raw.json",
                "02_ocr_blocks.json",
                "03_entities.json",
                "04_ocr_entity_boxes.json",
                "04_ocr_entity_boxes.png",
                "05_visual_boxes.json",
                "05_visual_boxes.png",
                "06_merged_boxes.json",
                "06_merged_boxes.png",
                "07_mask_plan.json",
                "08_preview.png",
            ],
        }
    )
    _json_dump(output_dir / "00_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run image anonymization flow with intermediate dumps.")
    parser.add_argument(
        "--image",
        default=str(Path(__file__).resolve().parent / "333.jpg"),
        help="Input image path",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output directory (default: unittest/output/<stem>)",
    )
    args = parser.parse_args()

    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.output).resolve() if args.output else image_path.parent / "output" / image_path.stem
    asyncio.run(run_flow(image_path, output_dir))
    print(f"\nArtifacts written to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
