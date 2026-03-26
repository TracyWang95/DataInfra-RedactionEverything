"""Pipeline 磁盘快照合并：glm_vision 迁移与 has_image 预置（发布前契约）。"""
from app.api.vision_pipeline import (
    PRESET_PIPELINES,
    PipelineMode,
    merge_pipeline_disk_snapshot,
)


def test_merge_empty_snapshot_returns_presets():
    out = merge_pipeline_disk_snapshot(None)
    assert set(out.keys()) == {"ocr_has", "has_image"}
    assert out["has_image"].mode == PipelineMode.HAS_IMAGE
    assert len(out["has_image"].types) == 21


def test_merge_drops_glm_vision_key():
    out = merge_pipeline_disk_snapshot(
        {
            "glm_vision": {
                "mode": "glm_vision",
                "enabled": True,
                "name": "X",
                "description": "d",
                "types": [],
            },
            "ocr_has": {
                "mode": "ocr_has",
                "enabled": True,
                "name": "OCR",
                "description": "d",
                "types": [],
            },
        }
    )
    assert "glm_vision" not in out
    assert "ocr_has" in out


def test_merge_rewrites_glm_vision_mode_to_has_image():
    face_type = {
        "id": "face",
        "name": "人脸",
        "description": None,
        "examples": [],
        "color": "#111111",
        "enabled": True,
        "order": 0,
    }
    out = merge_pipeline_disk_snapshot(
        {
            "has_image": {
                "mode": "glm_vision",
                "enabled": False,
                "name": "Legacy GLM",
                "description": "old",
                "types": [face_type],
            },
        }
    )
    merged = out["has_image"]
    assert merged.mode == PipelineMode.HAS_IMAGE
    assert merged.enabled is False
    assert len(merged.types) == 1
    assert merged.types[0].id == "face"


def test_merge_has_image_types_align_with_preset_count():
    out = merge_pipeline_disk_snapshot({})
    assert len(out["has_image"].types) == len(PRESET_PIPELINES["has_image"].types)
