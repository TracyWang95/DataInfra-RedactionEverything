"""小图自适应放大 (立案告知书457px实证: 原生分辨率进ViT召回波动).

_resize_for_inference 从"只缩"改为"缩到上界/放大到推理操作点区间":长边>max缩,
长边<upscale_target放大到target(Lanczos),之间不动。upscale_target=既有物理推理
尺寸(min(MIN_SIDE,max)),小于它=ViT patch预算不足的物理事实,非魔法数字。
默认upscale_target=0保持旧行为(字节等价)。
"""
from PIL import Image

from scripts.locate_anything_eval import _resize_for_inference


def _img(w, h):
    return Image.new("RGB", (w, h), "white")


def test_default_no_upscale_byte_equivalent():
    # upscale_target defaults 0 -> small image untouched (old behavior)
    im = _img(457, 646)
    assert _resize_for_inference(im, 1280).size == (457, 646)


def test_small_image_upscaled_to_target():
    im = _img(457, 646)
    out = _resize_for_inference(im, 1280, upscale_target=1280)
    assert max(out.size) == 1280
    assert out.size == (int(round(457 * 1280 / 646)), 1280)  # aspect kept


def test_large_image_still_shrinks_and_never_upscales():
    im = _img(2000, 3000)
    out = _resize_for_inference(im, 1280, upscale_target=1280)
    assert max(out.size) == 1280  # shrunk, not upscaled


def test_between_bounds_untouched():
    im = _img(1000, 900)  # <1280 longest, but target=800 -> no upscale needed
    out = _resize_for_inference(im, 1280, upscale_target=800)
    assert out.size == (1000, 900)


def test_oom_clamp_target_never_exceeds_attempt_budget():
    # OOM ladder passes a shrunk attempt_side; upscale_target clamped to it
    im = _img(457, 646)
    out = _resize_for_inference(im, 640, upscale_target=640)
    assert max(out.size) == 640  # upscaled only to the OOM-safe budget, not 1280
