"""Warm up the current OCR, semantic, and visual feature services."""

from __future__ import annotations

import base64
import os
import sys
import time
from io import BytesIO

import httpx
from PIL import Image, ImageDraw

HAS_TEXT_BASE_URL = os.environ.get("HAS_TEXT_VLLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
HAS_TEXT_URL = f"{HAS_TEXT_BASE_URL}/chat/completions"
HAS_TEXT_MODELS_URL = f"{HAS_TEXT_BASE_URL}/models"
HAS_TEXT_MODEL = os.environ.get("HAS_TEXT_MODEL_NAME", "HaS_4.0_0.6B")

OCR_BASE_URL = os.environ.get("OCR_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
OCR_URL = f"{OCR_BASE_URL}/ocr"
OCR_STRUCTURE_URL = f"{OCR_BASE_URL}/structure"

VISUAL_BASE_URL = (
    os.environ.get("VISUAL_FEATURES_BASE_URL")
    or "http://127.0.0.1:8090"
).rstrip("/")
VISUAL_HEALTH_URL = f"{VISUAL_BASE_URL}/health"
VISUAL_DETECT_URL = f"{VISUAL_BASE_URL}/detect"
VISUAL_CHAT_URL = (
    f"{VISUAL_BASE_URL}/chat/completions"
    if VISUAL_BASE_URL.endswith("/v1")
    else f"{VISUAL_BASE_URL}/v1/chat/completions"
)
VISUAL_MODELS_URL = f"{VISUAL_BASE_URL}/models" if VISUAL_BASE_URL.endswith("/v1") else f"{VISUAL_BASE_URL}/v1/models"
VISUAL_MODEL = (
    os.environ.get("VISUAL_FEATURES_MODEL_NAME")
    or os.environ.get("LOCATE_ANYTHING_MODEL_NAME")
    or "LocateAnything-3B"
)
VISUAL_MAX_TOKENS = int(os.environ.get("LOCATE_ANYTHING_MAX_NEW_TOKENS", "8192"))
# Long side (px) the visual server resizes inference images to; warm at this size
# so MoonViT autotunes/captures the SAME patch grid a real scanned page hits.
VISUAL_WARMUP_LONG_SIDE = int(os.environ.get("LOCATE_ANYTHING_MAX_IMAGE_SIDE", "1280"))
# Production default visual categories (matches preset_pipeline_types default-enabled).
VISUAL_WARMUP_CATEGORIES = ["official_seal", "signature"]
# Repeat the visual detect until a pass actually reaches the warm steady state:
# the MoonViT encode settles over several iterations (cold autotune + cuDNN
# benchmark + the expandable-segments allocator caching its segments under memory
# pressure), and the per-pass curve is noisy (pass 2 has measured anywhere from
# 17s to 31s), so a relative-plateau test stops too early. Instead keep warming
# until a pass finishes under an absolute target (warm), with a min/max bound.
VISUAL_WARMUP_MIN_PASSES = int(os.environ.get("VISUAL_FEATURES_WARMUP_MIN_PASSES", "3"))
VISUAL_WARMUP_MAX_PASSES = int(os.environ.get("VISUAL_FEATURES_WARMUP_MAX_PASSES", "8"))
VISUAL_WARMUP_TARGET_SECONDS = float(os.environ.get("VISUAL_FEATURES_WARMUP_TARGET_SECONDS", "8.0"))

TIMEOUT = 180.0
DEFAULT_MAX_WAIT = int(os.environ.get("WARMUP_MAX_WAIT_SECONDS", "120"))


def _png_base64(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _white_pixel_png_base64() -> str:
    return _png_base64(Image.new("RGB", (2, 2), "white"))


def _document_image_base64() -> str:
    image = Image.new("RGB", (640, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((48, 48, 592, 852), outline=(210, 210, 210), width=2)
    draw.text((80, 92), "Patient: Zhang San    Age: 61", fill="black")
    draw.text((80, 148), "Anesthesia visit record", fill="black")
    draw.line((80, 210, 560, 210), fill=(80, 80, 80), width=2)
    draw.text((80, 240), "Doctor signature:", fill="black")
    draw.line((240, 305, 306, 262), fill=(35, 35, 35), width=4)
    draw.line((306, 262, 352, 324), fill=(35, 35, 35), width=4)
    draw.line((352, 324, 438, 278), fill=(35, 35, 35), width=4)
    draw.ellipse((372, 228, 504, 360), outline=(150, 45, 45), width=5)
    draw.rectangle((80, 430, 560, 690), outline="black", width=2)
    for y in (520, 610):
        draw.line((80, y, 560, y), fill="black", width=2)
    for x in (240, 400):
        draw.line((x, 430, x, 690), fill="black", width=2)
    draw.text((116, 464), "Name", fill="black")
    draw.text((276, 464), "Result", fill="black")
    draw.text((436, 464), "Date", fill="black")
    draw.text((116, 554), "Alice", fill="black")
    draw.text((276, 554), "ASAT", fill="black")
    draw.text((436, 554), "2026-05-06", fill="black")
    return _png_base64(image)


def _large_document_image_base64() -> str:
    """A portrait page sized so the long side equals VISUAL_WARMUP_LONG_SIDE.

    A real scanned A4 page is resized to ~904x1280 before MoonViT; this synthetic
    page hits the same patch grid, so warming on it captures the CUDA graphs and
    cuDNN autotune the first real /detect would otherwise pay (cold first detect
    was 30s+). It also draws a round seal + a signature stroke so the detector has
    something to localize."""
    long_side = max(640, VISUAL_WARMUP_LONG_SIDE)
    height = long_side
    width = max(320, round(long_side * 0.707))  # A4 portrait aspect (1 : 1.414)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin = round(width * 0.05)
    draw.rectangle((margin, margin, width - margin, height - margin), outline=(210, 210, 210), width=3)
    line_gap = round(height * 0.04)
    for index in range(1, 18):
        y = margin * 2 + index * line_gap
        if y > height - margin * 3:
            break
        draw.line((margin * 2, y, width - margin * 2, y), fill=(70, 70, 70), width=2)
    draw.ellipse(
        (width - round(width * 0.30), height - round(height * 0.24),
         width - round(width * 0.11), height - round(height * 0.11)),
        outline=(170, 40, 40), width=6,
    )
    sx, sy = round(width * 0.14), height - round(height * 0.18)
    draw.line((sx, sy, sx + round(width * 0.10), sy - round(height * 0.04)), fill=(30, 30, 30), width=5)
    draw.line((sx + round(width * 0.10), sy - round(height * 0.04), sx + round(width * 0.22), sy), fill=(30, 30, 30), width=5)
    return _png_base64(image)


def _post_json(url: str, payload: dict, *, timeout: float = TIMEOUT) -> httpx.Response:
    response = httpx.post(url, json=payload, timeout=timeout, trust_env=False)
    response.raise_for_status()
    return response


def _get_json(url: str, *, timeout: float = 5.0) -> dict | None:
    try:
        response = httpx.get(url, timeout=timeout, trust_env=False)
        if response.status_code == 200:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return None
    return None


def _service_ready_health(url: str) -> bool:
    payload = _get_json(url)
    if payload is None:
        return False
    status = str(payload.get("status", "")).lower()
    # Only "loaded but currently busy" statuses count as ready; "loading"/
    # "starting" mean the model is NOT loaded yet and must keep us waiting.
    if status in {"busy", "running", "processing", "inferencing", "warming_up"}:
        return True
    return bool(payload.get("ready", True))


def _service_ready_models(url: str) -> bool:
    payload = _get_json(url)
    return bool(payload and isinstance(payload.get("data"), list))


def wait_for_services(max_wait: int = DEFAULT_MAX_WAIT) -> bool:
    print("[start] waiting for model services...")
    has_ready = False
    ocr_ready = False
    visual_ready = False

    for second in range(max_wait):
        if not has_ready:
            has_ready = _service_ready_models(HAS_TEXT_MODELS_URL)
            if has_ready:
                print("[start] [OK] HaS Text ready")

        if not ocr_ready:
            ocr_ready = _service_ready_health(f"{OCR_BASE_URL}/health")
            if ocr_ready:
                print("[start] [OK] PaddleOCR ready")

        if not visual_ready:
            visual_ready = _service_ready_health(VISUAL_HEALTH_URL) and _service_ready_models(VISUAL_MODELS_URL)
            if visual_ready:
                print("[start] [OK] LocateAnything ready")

        if has_ready and ocr_ready and visual_ready:
            return True

        if second % 5 == 0:
            print(
                f"[start] waiting ({second}s) "
                f"HaS={'OK' if has_ready else '...'} "
                f"OCR={'OK' if ocr_ready else '...'} "
                f"Visual={'OK' if visual_ready else '...'}"
            )
        time.sleep(1)

    return False


def warmup_has_text() -> bool:
    print("[warmup] HaS Text ...")
    try:
        start = time.perf_counter()
        _post_json(
            HAS_TEXT_URL,
            {
                "model": HAS_TEXT_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            'Recognize these entity types: ["姓名","电话"]. '
                            'Return strict JSON only. <text>张三 电话 13812345678</text>'
                        ),
                    }
                ],
                "max_tokens": 128,
                "temperature": 0.0,
            },
        )
        print(f"[warmup] [OK] HaS Text done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] HaS Text failed: {exc}")
        return False


def warmup_paddle_ocr() -> bool:
    if os.environ.get("OCR_VL_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        print("[warmup] [SKIP] PaddleOCR-VL disabled (PP-StructureV3-only mode)")
        return True
    print("[warmup] PaddleOCR-VL ...")
    try:
        start = time.perf_counter()
        _post_json(OCR_URL, {"image": _document_image_base64(), "max_new_tokens": 128})
        print(f"[warmup] [OK] PaddleOCR-VL done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] PaddleOCR-VL failed: {exc}")
        return False


def warmup_pp_structure() -> bool:
    if os.environ.get("OCR_STRUCTURE_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        print("[warmup] [SKIP] PP-StructureV3 disabled")
        return True
    if os.environ.get("OCR_STRUCTURE_WARMUP", "1").strip().lower() in {"0", "false", "no", "off"}:
        print("[warmup] [SKIP] PP-StructureV3 disabled")
        return True
    print("[warmup] PP-StructureV3 ...")
    try:
        start = time.perf_counter()
        _post_json(
            OCR_STRUCTURE_URL,
            {
                "image": _document_image_base64(),
                "use_ocr_results_with_table_cells": True,
                "use_table_orientation_classify": False,
            },
        )
        print(f"[warmup] [OK] PP-StructureV3 done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] PP-StructureV3 failed: {exc}")
        return False


def warmup_visual_detect() -> bool:
    print(f"[warmup] LocateAnything /detect (long_side={VISUAL_WARMUP_LONG_SIDE}, warm-to-plateau) ...")
    image_b64 = _large_document_image_base64()
    ok = False
    for attempt in range(1, VISUAL_WARMUP_MAX_PASSES + 1):
        try:
            start = time.perf_counter()
            _post_json(
                VISUAL_DETECT_URL,
                {"image_base64": image_b64, "categories": VISUAL_WARMUP_CATEGORIES, "conf": 0.25},
            )
            dt = time.perf_counter() - start
            ok = True
            print(f"[warmup] [OK] LocateAnything /detect pass {attempt} done in {dt:.2f}s")
            # Keep warming until a pass actually reaches the warm steady state.
            if attempt >= VISUAL_WARMUP_MIN_PASSES and dt < VISUAL_WARMUP_TARGET_SECONDS:
                print(f"[warmup] [OK] LocateAnything /detect warm ({dt:.2f}s < {VISUAL_WARMUP_TARGET_SECONDS:.0f}s target)")
                break
        except Exception as exc:
            print(f"[warmup] [FAIL] LocateAnything /detect pass {attempt} failed: {exc}")
            ok = False
            break
    return ok


def warmup_visual_chat() -> bool:
    print("[warmup] LocateAnything visual grounding ...")
    try:
        start = time.perf_counter()
        _post_json(
            VISUAL_CHAT_URL,
            {
                "model": VISUAL_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{_large_document_image_base64()}"},
                            },
                            {
                                "type": "text",
                                "text": "Locate all handwritten signatures in box format.",
                            },
                        ],
                    }
                ],
                "max_tokens": VISUAL_MAX_TOKENS,
                "temperature": 0.1,
                "top_p": 0.6,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "thinking": {"type": "disabled"},
                "enable_thinking": False,
            },
            timeout=float(os.environ.get("VISUAL_FEATURES_WARMUP_TIMEOUT", "240")),
        )
        print(f"[warmup] [OK] LocateAnything visual grounding done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] LocateAnything visual grounding failed: {exc}")
        return False


def main() -> None:
    print("=" * 50)
    print("Model Warmup Script")
    print("=" * 50)

    if not wait_for_services():
        print("[ERROR] Services not ready in time")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Warming up models...")
    print("=" * 50 + "\n")

    checks = [
        warmup_has_text(),
        warmup_paddle_ocr(),
        warmup_pp_structure(),
        warmup_visual_detect(),
        warmup_visual_chat(),
    ]
    all_ok = all(checks)

    print("\n" + "=" * 50)
    if all_ok:
        print("[OK] All models warmed up!")
    else:
        print("[ERROR] Some models failed to warm up")
    print("=" * 50)
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
