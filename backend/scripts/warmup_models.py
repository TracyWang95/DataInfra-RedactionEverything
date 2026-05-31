"""Warm up local model services before the first real recognition request.

This script is intentionally conservative: it only calls already-running
services and never starts or stops model processes.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from io import BytesIO

import httpx
from PIL import Image, ImageDraw

HAS_BASE_URL = os.environ.get("HAS_TEXT_VLLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
HAS_URL = f"{HAS_BASE_URL}/chat/completions"
HAS_MODEL = os.environ.get("HAS_TEXT_MODEL_NAME", "HaS_4.0_0.6B")
HAS_IMAGE_HEALTH = "http://127.0.0.1:8081/health"
HAS_IMAGE_DETECT = "http://127.0.0.1:8081/detect"
OCR_BASE_URL = os.environ.get("OCR_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
OCR_URL = f"{OCR_BASE_URL}/ocr"
OCR_STRUCTURE_URL = f"{OCR_BASE_URL}/structure"
VLM_URL = os.environ.get("VLM_WARMUP_URL", "http://127.0.0.1:8090/v1/chat/completions")
VLM_MODEL = os.environ.get("VLM_MODEL_NAME", "GLM-4.6V-Flash-Q4")
TIMEOUT = 180.0
DEFAULT_MAX_WAIT = int(os.environ.get("WARMUP_MAX_WAIT_SECONDS", "90"))


def _png_base64(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _white_pixel_png_base64() -> str:
    return _png_base64(Image.new("RGB", (1, 1), "white"))


def _signature_warmup_image_base64() -> str:
    image = Image.new("RGB", (427, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((42, 68, 385, 568), outline=(220, 220, 220), width=2)
    draw.text((72, 120), "Company: Example Technology Co., Ltd.", fill="black")
    draw.text((72, 180), "Representative (signature):", fill="black")
    draw.line((72, 248, 345, 248), fill=(150, 150, 150), width=2)
    draw.line((170, 232, 206, 214), fill=(40, 40, 40), width=3)
    draw.line((206, 214, 232, 238), fill=(40, 40, 40), width=3)
    draw.line((232, 238, 285, 206), fill=(40, 40, 40), width=3)
    draw.line((285, 206, 330, 226), fill=(40, 40, 40), width=3)
    draw.ellipse((238, 176, 346, 284), outline=(210, 38, 38), width=4)
    draw.text((72, 318), "Date: 2026-05-26", fill="black")
    return _png_base64(image)


def _signature_warmup_prompt() -> str:
    try:
        from app.services.pipeline_service import get_pipeline_types_for_mode
        from app.services.vlm_vision_service import VlmVisionService

        type_configs = [
            item
            for item in get_pipeline_types_for_mode("vlm", enabled_only=True)
            if getattr(item, "id", "") == "signature"
        ]
        if type_configs:
            return (
                VlmVisionService().build_prompt(type_configs)
                + "\nDetection view: full. Coordinates must be relative to the supplied image for this request."
            )
    except Exception as exc:
        print(f"[warmup] production signature prompt unavailable, using fallback: {exc}")
    return (
        "Task: detect handwritten signer names/signatures only. "
        "Box only visible handwritten ink strokes, not printed labels, company names, dates, seals, or blank lines. "
        'Return JSON only: {"objects":[{"type_id":"signature","label":"签字","box_2d":[0,0,0,0],"confidence":0.8}]}'
    )


def _table_png_base64() -> str:
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((48, 72, 592, 340), outline="black", width=3)
    for y in (150, 230):
        draw.line((48, y, 592, y), fill="black", width=2)
    for x in (228, 410):
        draw.line((x, 72, x, 340), fill="black", width=2)
    draw.text((84, 104), "Name", fill="black")
    draw.text((264, 104), "Amount", fill="black")
    draw.text((446, 104), "Date", fill="black")
    draw.text((84, 184), "Alice", fill="black")
    draw.text((264, 184), "12345", fill="black")
    draw.text((446, 184), "2026-05-06", fill="black")
    return _png_base64(image)


def _post_json(url: str, payload: dict, *, timeout: float = TIMEOUT) -> httpx.Response:
    response = httpx.post(url, json=payload, timeout=timeout, trust_env=False)
    response.raise_for_status()
    return response


def warmup_has_model() -> bool:
    print("[warmup] HaS Text ...")
    try:
        start = time.perf_counter()
        _post_json(
            HAS_URL,
            {
                "model": HAS_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            'Recognize the following entity types in the text.\n'
                            'Specified types:["姓名","电话"]\n'
                            'Return strict JSON only. Include only entity types that have matches in the text.\n'
                            'Never output empty arrays. Do not explain.\n'
                            '<text>张三 电话 13812345678</text>'
                        ),
                    },
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


def warmup_has_image_model() -> bool:
    print("[warmup] HaS Image ...")
    try:
        start = time.perf_counter()
        _post_json(HAS_IMAGE_DETECT, {"image_base64": _white_pixel_png_base64(), "conf": 0.25})
        print(f"[warmup] [OK] HaS Image done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] HaS Image failed: {exc}")
        return False


def warmup_ocr_vl() -> bool:
    print("[warmup] PaddleOCR-VL ...")
    try:
        start = time.perf_counter()
        _post_json(OCR_URL, {"image": _white_pixel_png_base64(), "max_new_tokens": 64})
        print(f"[warmup] [OK] PaddleOCR-VL done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] PaddleOCR-VL failed: {exc}")
        return False


def warmup_ocr_structure() -> bool:
    print("[warmup] PP-StructureV3 ...")
    try:
        start = time.perf_counter()
        _post_json(
            OCR_STRUCTURE_URL,
            {
                "image": _table_png_base64(),
                "use_ocr_results_with_table_cells": True,
                "use_table_orientation_classify": False,
            },
        )
        print(f"[warmup] [OK] PP-StructureV3 done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] PP-StructureV3 failed: {exc}")
        return False


def warmup_vlm() -> bool:
    print("[warmup] GLM VLM production signature path ...")
    try:
        start = time.perf_counter()
        _post_json(
            VLM_URL,
            {
                "model": VLM_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{_signature_warmup_image_base64()}"},
                            },
                            {
                                "type": "text",
                                "text": _signature_warmup_prompt(),
                            },
                        ],
                    },
                ],
                "max_tokens": 384,
                "temperature": 0.1,
                "top_p": 0.6,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "thinking": {"type": "disabled"},
                "enable_thinking": False,
            },
            timeout=float(os.environ.get("VLM_WARMUP_TIMEOUT", "120")),
        )
        print(f"[warmup] [OK] GLM VLM done in {time.perf_counter() - start:.2f}s")
        return True
    except Exception as exc:
        print(f"[warmup] [FAIL] GLM VLM failed: {exc}")
        return False


def check_service(url: str) -> bool:
    try:
        response = httpx.get(url.replace("/v1/chat/completions", "/health"), timeout=5.0, trust_env=False)
        if response.status_code == 200:
            return True
    except Exception:
        pass
    try:
        response = httpx.get(url.replace("/v1/chat/completions", "/v1/models"), timeout=5.0, trust_env=False)
        return response.status_code == 200
    except Exception:
        return False


def check_vlm_service() -> bool:
    try:
        base = VLM_URL.rsplit("/chat/completions", 1)[0]
        response = httpx.get(f"{base}/models", timeout=5.0, trust_env=False)
        return response.status_code == 200
    except Exception:
        return False


def probe_has_image() -> tuple[str, bool]:
    try:
        response = httpx.get(HAS_IMAGE_HEALTH, timeout=5.0, trust_env=False)
        if response.status_code != 200:
            return "down", False
        payload = response.json()
        if payload.get("ready"):
            return "ready", True
        return "unavailable", False
    except Exception:
        return "down", False


def wait_for_services(max_wait: int = DEFAULT_MAX_WAIT) -> bool:
    print("[start] waiting for model services...")
    has_ready = False
    ocr_ready = False
    vlm_ready = False

    for second in range(max_wait):
        if not has_ready:
            has_ready = check_service(HAS_URL)
            if has_ready:
                print("[start] [OK] HaS Text ready")

        if not ocr_ready:
            try:
                response = httpx.get(f"{OCR_BASE_URL}/health", timeout=3.0, trust_env=False)
                if response.status_code == 200 and response.json().get("ready"):
                    ocr_ready = True
                    print("[start] [OK] OCR ready")
            except Exception:
                pass

        if not vlm_ready:
            vlm_ready = check_vlm_service()
            if vlm_ready:
                print("[start] [OK] GLM VLM ready")

        state, loaded = probe_has_image()
        if state == "ready" and loaded and second % 15 == 0:
            print("[start] [OK] HaS Image ready")
        elif state == "unavailable" and second % 20 == 0:
            print("[start] [WARN] HaS Image is reachable but not ready")

        if has_ready and ocr_ready and vlm_ready and state == "ready" and loaded:
            return True

        if second % 5 == 0:
            image_state = "OK" if loaded else ("up" if state == "unavailable" else "...")
            print(
                f"[start] waiting ({second}s) "
                f"HaS={'OK' if has_ready else '...'} "
                f"HaS-Image={image_state} OCR={'OK' if ocr_ready else '...'} "
                f"VLM={'OK' if vlm_ready else '...'}"
            )
        time.sleep(1)

    print(
        "[start] services are not reachable from this shell. "
        "If /health/services is online, run this script inside the same WSL/container network as the model services."
    )
    state, loaded = probe_has_image()
    return has_ready and ocr_ready and vlm_ready and state == "ready" and loaded


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

    has_ok = warmup_has_model()
    print()
    _, image_loaded = probe_has_image()
    if image_loaded:
        image_ok = warmup_has_image_model()
    else:
        print("[warmup] [SKIP] HaS Image weights are not loaded")
        image_ok = True
    print()
    ocr_ok = warmup_ocr_vl()
    print()
    structure_ok = warmup_ocr_structure()
    print()
    vlm_ok = warmup_vlm()

    print("\n" + "=" * 50)
    all_ok = has_ok and image_ok and ocr_ok and structure_ok and vlm_ok
    if all_ok:
        print("[OK] All models warmed up!")
    else:
        print("[ERROR] Some models failed to warm up")
    print("=" * 50)
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
