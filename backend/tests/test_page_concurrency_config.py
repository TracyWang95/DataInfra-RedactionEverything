"""P1-2 调度上限放宽：GPU 饱和率可配、视觉合并趟并发可配、页并发 validator 放宽到 8。"""
from __future__ import annotations

from app.core.config import settings
from app.services.task_queue import (
    _effective_vision_page_concurrency,
    _vision_page_concurrency_reason,
)


def _gpu(used_mb: int, total_mb: int = 32607):
    return {"used_mb": used_mb, "total_mb": total_mb}


def test_saturation_ratio_default_downgrades_at_90(monkeypatch):
    monkeypatch.setattr(settings, "GPU_SATURATION_RATIO", 0.90, raising=False)
    # 92% used -> forced to 1
    assert _effective_vision_page_concurrency({}, 6, 3, gpu_memory=_gpu(30000)) == 1
    assert (
        _vision_page_concurrency_reason(6, 3, 1, _gpu(30000)) == "gpu_memory_high"
    )


def test_saturation_ratio_configurable_avoids_false_positive(monkeypatch):
    # 双卡生产静态驻留 ~80%：0.95 阈值下 92% 不再误判饱和
    monkeypatch.setattr(settings, "GPU_SATURATION_RATIO", 0.95, raising=False)
    assert _effective_vision_page_concurrency({}, 6, 3, gpu_memory=_gpu(30000)) == 3
    assert _vision_page_concurrency_reason(6, 3, 3, _gpu(30000)) == "configured"
    # 96% used -> still downgrades
    assert _effective_vision_page_concurrency({}, 6, 3, gpu_memory=_gpu(31400)) == 1


def test_page_concurrency_still_capped_by_pages(monkeypatch):
    monkeypatch.setattr(settings, "GPU_SATURATION_RATIO", 0.95, raising=False)
    assert _effective_vision_page_concurrency({}, 2, 8, gpu_memory=_gpu(1000)) == 2


def test_validators_clamp():
    settings_cls = type(settings)
    assert settings_cls(BATCH_RECOGNITION_PAGE_CONCURRENCY=8).BATCH_RECOGNITION_PAGE_CONCURRENCY == 8
    assert settings_cls(BATCH_RECOGNITION_PAGE_CONCURRENCY=9).BATCH_RECOGNITION_PAGE_CONCURRENCY == 8
    assert settings_cls(BATCH_RECOGNITION_PAGE_CONCURRENCY=0).BATCH_RECOGNITION_PAGE_CONCURRENCY == 1
    assert settings_cls(BATCH_VISUAL_MERGE_PAGE_CONCURRENCY=2).BATCH_VISUAL_MERGE_PAGE_CONCURRENCY == 2
    assert settings_cls(BATCH_VISUAL_MERGE_PAGE_CONCURRENCY=9).BATCH_VISUAL_MERGE_PAGE_CONCURRENCY == 4
    assert settings_cls(BATCH_VISUAL_MERGE_PAGE_CONCURRENCY=0).BATCH_VISUAL_MERGE_PAGE_CONCURRENCY == 1
    assert settings_cls(GPU_SATURATION_RATIO=0.95).GPU_SATURATION_RATIO == 0.95
    assert settings_cls(GPU_SATURATION_RATIO=1.5).GPU_SATURATION_RATIO == 0.99
    assert settings_cls(GPU_SATURATION_RATIO=0.1).GPU_SATURATION_RATIO == 0.5


def test_defaults_keep_current_behavior():
    settings_cls = type(settings)
    fresh = settings_cls()
    assert fresh.BATCH_VISUAL_MERGE_PAGE_CONCURRENCY == 1
    assert abs(fresh.GPU_SATURATION_RATIO - 0.90) < 1e-9
