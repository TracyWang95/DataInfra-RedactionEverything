from __future__ import annotations

from app.core.health_checks import (
    MINERU_PIPELINE_CONFIG_ID,
    PADDLE_OCR_CONFIG_ID,
    classify_ocr_adapter,
)


def test_classify_ocr_adapter_mineru():
    assert classify_ocr_adapter("MinerU-pipeline (ModelScope)") == MINERU_PIPELINE_CONFIG_ID


def test_classify_ocr_adapter_paddle():
    assert classify_ocr_adapter("PaddleOCR-VL-1.6-0.9B") == PADDLE_OCR_CONFIG_ID
    assert classify_ocr_adapter("PP-StructureV3") == PADDLE_OCR_CONFIG_ID
