"""
vision subpackage - focused modules split from hybrid_vision_service.py.

Re-exports for backward compatibility:
    from app.services.vision import ocr_pipeline, image_pipeline, region_merger
"""
from app.services.vision.ocr_pipeline import (
    prepare_image,
    run_paddle_ocr,
    extract_table_cells,
    expand_table_blocks,
    run_has_text_analysis,
    match_entities_to_ocr,
    apply_regex_rules,
)
from app.services.vision.image_pipeline import (
    match_ocr_to_vlm,
    draw_regions_on_image,
    apply_redaction,
)
from app.services.vision.region_merger import (
    calc_iou_boxes,
    calc_iou_regions,
    merge_regions,
)

__all__ = [
    # ocr_pipeline
    "prepare_image",
    "run_paddle_ocr",
    "extract_table_cells",
    "expand_table_blocks",
    "run_has_text_analysis",
    "match_entities_to_ocr",
    "apply_regex_rules",
    # image_pipeline
    "match_ocr_to_vlm",
    "draw_regions_on_image",
    "apply_redaction",
    # region_merger
    "calc_iou_boxes",
    "calc_iou_regions",
    "merge_regions",
]
