"""
LocateAnything-3B service adapter.

One model process exposes both visual feature interfaces used by the app:
- /health and /detect for fixed visual feature presets.
- OpenAI-compatible /v1/models and /v1/chat/completions for custom labels.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import time
from io import BytesIO
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from locate_anything_eval import LocateAnythingWorker, _parse_boxes, _resize_for_inference


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() not in {"", "0", "false", "no", "off"}


MODEL_NAME = os.environ.get("LOCATE_ANYTHING_MODEL_NAME", "LocateAnything-3B")
DEFAULT_MAX_SIDE = int(os.environ.get("LOCATE_ANYTHING_MAX_IMAGE_SIDE", "1280"))
DEFAULT_MIN_SIDE = int(os.environ.get("LOCATE_ANYTHING_MIN_IMAGE_SIDE", "1280"))
DEFAULT_MAX_NEW_TOKENS = int(os.environ.get("LOCATE_ANYTHING_MAX_NEW_TOKENS", "8192"))
DEFAULT_GENERATION_MODE = os.environ.get("LOCATE_ANYTHING_GENERATION_MODE", "hybrid")
DEFAULT_TEMPERATURE = float(os.environ.get("LOCATE_ANYTHING_TEMPERATURE", "0.7"))
FAST_FIRST_ENABLED = _env_flag("LOCATE_ANYTHING_FAST_FIRST", "1")
FAST_FIRST_FALLBACK_ON_EMPTY = _env_flag("LOCATE_ANYTHING_FAST_FIRST_FALLBACK_ON_EMPTY", "1")
SIGNATURE_TILE_FALLBACK_MAX_TILES = int(os.environ.get("LOCATE_ANYTHING_SIGNATURE_TILE_FALLBACK_MAX_TILES", "1"))
SIGNATURE_MAX_SIDE = int(os.environ.get("LOCATE_ANYTHING_SIGNATURE_MAX_IMAGE_SIDE", str(min(DEFAULT_MAX_SIDE, 1280))))
SIGNATURE_TILE_FALLBACK_MAX_SIDE = int(
    os.environ.get("LOCATE_ANYTHING_SIGNATURE_TILE_MAX_IMAGE_SIDE", str(min(SIGNATURE_MAX_SIDE, 1280)))
)
VALID_GENERATION_MODES = {"fast", "hybrid", "slow"}


def _normalize_generation_mode(value: str | None) -> str:
    mode = str(value or DEFAULT_GENERATION_MODE).strip().lower()
    return mode if mode in VALID_GENERATION_MODES else "hybrid"


def _generation_mode_sequence(mode: str, fast_first: bool) -> list[str]:
    mode = _normalize_generation_mode(mode)
    if fast_first and mode != "fast":
        return ["fast", mode]
    return [mode]


def trim_cuda_cache(label: str) -> None:
    try:
        import gc
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
            print(f"[LocateAnything] cuda cache trimmed after {label}", flush=True)
    except Exception:
        pass


def _is_cuda_capacity_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "out of memory" in text
        or "cudacachingallocator" in text
        or "cuda error" in text
        or "cuda out" in text
        or "make_resident" in text
    )


def _adaptive_image_sides(requested: int) -> list[int]:
    floor = max(640, min(DEFAULT_MIN_SIDE, requested))
    candidates = [requested, 2048, 1920, 1792, 1600, 1536, 1280, 1024]
    result: list[int] = []
    for side in candidates:
        side = int(side)
        if side > requested or side < floor or side in result:
            continue
        result.append(side)
    if requested not in result:
        result.insert(0, requested)
    return result


FIXED_VISUAL_PROMPTS: dict[str, str] = {
    "face": "human face",
    "fingerprint": "fingerprint",
    "palmprint": "palmprint",
    "id_card": "identity card or national ID card",
    "hk_macau_permit": "Hong Kong or Macau travel permit card",
    "passport": "passport",
    "employee_badge": "employee badge or work ID card",
    "license_plate": "vehicle license plate",
    "bank_card": "bank card or credit card",
    "physical_key": "physical key",
    "receipt": "receipt or shopping receipt",
    "shipping_label": "shipping label or delivery waybill",
    "official_seal": "official seal stamp impression, company chop, or inked stamp mark. Do not locate handwritten signatures, printed labels, or table lines",
    "whiteboard": "whiteboard",
    "sticky_note": "sticky note",
    "mobile_screen": "mobile phone screen",
    "monitor_screen": "computer monitor screen",
    "medical_wristband": "medical wristband",
    "qr_code": "QR code",
    "barcode": "barcode",
    "paper": "paper document page",
    "signature": "handwritten signature or handwritten signer name; not printed labels, dates, seals, table lines, or plain printed text",
}

PAGE_SCALE_CATEGORIES = {
    "paper",
    "receipt",
    "shipping_label",
    "id_card",
    "hk_macau_permit",
    "passport",
    "bank_card",
    "employee_badge",
    "whiteboard",
    "mobile_screen",
    "monitor_screen",
}


CUSTOM_VISUAL_PROMPTS: dict[str, str] = {
    "signature": (
        "Locate all the instances that match the following description: actual visible handwritten "
        "signatures or handwritten signer names in this document image. Do not locate printed labels, "
        "dates, seals, table lines, horizontal rules, blank fields, regular printed text, or whole "
        "signing areas. Use one tight box around each handwritten signature stroke only."
    ),
}


class DetectRequest(BaseModel):
    image_base64: str = Field(...)
    conf: float = Field(default=0.25, ge=0.01, le=1.0)
    categories: list[str] | None = None
    generation_mode: str | None = None
    fast_first: bool | None = None
    signature_fallback: bool = True
    max_image_side: int | None = None


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool | None = False


class LocateService:
    def __init__(self) -> None:
        self.worker: LocateAnythingWorker | None = None
        self.model_path = ""
        self.backend = "hf"
        self.dtype = "bfloat16"
        self.ready = False
        self.lock = asyncio.Lock()

    def configure(self, model_path: str, backend: str, dtype: str) -> None:
        self.model_path = model_path
        self.backend = backend
        self.dtype = dtype

    def load(self) -> None:
        self.worker = LocateAnythingWorker(self.model_path, backend=self.backend, dtype_name=self.dtype)
        self.ready = True

    async def predict_boxes(
        self,
        image: Image.Image,
        prompt: str,
        *,
        max_image_side: int = DEFAULT_MAX_SIDE,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
        generation_mode: str = DEFAULT_GENERATION_MODE,
        temperature: float = DEFAULT_TEMPERATURE,
        fast_first: bool | None = None,
        fallback_when_no_boxes: bool = True,
    ) -> tuple[str, list[dict[str, Any]], tuple[int, int]]:
        if self.worker is None or not self.ready:
            raise HTTPException(status_code=503, detail="LocateAnything model is not ready")
        source_size = image.size
        last_capacity_error: BaseException | None = None
        requested_mode = _normalize_generation_mode(generation_mode)
        mode_sequence = _generation_mode_sequence(
            requested_mode,
            FAST_FIRST_ENABLED if fast_first is None else bool(fast_first),
        )
        for attempt_side in _adaptive_image_sides(max_image_side):
            inference_image = _resize_for_inference(image, attempt_side)
            scale_x = inference_image.width / source_size[0] if source_size[0] else 1.0
            scale_y = inference_image.height / source_size[1] if source_size[1] else 1.0
            last_answer = ""
            last_mapped: list[dict[str, Any]] = []
            retry_smaller_side = False
            for mode in mode_sequence:
                async with self.lock:
                    start = time.perf_counter()
                    try:
                        answer = await asyncio.to_thread(
                            self.worker.predict,
                            inference_image,
                            prompt,
                            mode,
                            max_new_tokens,
                            temperature,
                        )
                    except RuntimeError as exc:
                        trim_cuda_cache(f"predict-failed-{attempt_side}-{mode}")
                        if not _is_cuda_capacity_error(exc):
                            raise
                        last_capacity_error = exc
                        retry_smaller_side = True
                        print(
                            "[LocateAnything] capacity retry "
                            f"prompt={prompt[:72]!r} mode={mode} side={attempt_side} "
                            f"size={inference_image.width}x{inference_image.height} error={str(exc)[:160]!r}",
                            flush=True,
                        )
                        break
                    finally:
                        trim_cuda_cache("predict")
                    elapsed = time.perf_counter() - start
                    print(
                        f"[LocateAnything] prompt={prompt[:72]!r} mode={mode} "
                        f"boxes_inference_size={inference_image.width}x{inference_image.height} "
                        f"max_side={attempt_side} elapsed={elapsed:.2f}s",
                        flush=True,
                    )
                boxes = _parse_boxes(answer, inference_image.width, inference_image.height)
                mapped: list[dict[str, Any]] = []
                for box in boxes:
                    mapped.append(
                        {
                            **box,
                            "x": round(float(box["x"]) / scale_x, 2),
                            "y": round(float(box["y"]) / scale_y, 2),
                            "width": round(float(box["width"]) / scale_x, 2),
                            "height": round(float(box["height"]) / scale_y, 2),
                        }
                    )
                last_answer = answer
                last_mapped = mapped
                if mode == requested_mode or mapped or not fallback_when_no_boxes:
                    return answer, mapped, source_size
                print(
                    f"[LocateAnything] fast-first empty, fallback to {requested_mode} prompt={prompt[:72]!r}",
                    flush=True,
                )
            if retry_smaller_side:
                continue
            return last_answer, last_mapped, source_size
        else:
            raise HTTPException(
                status_code=503,
                detail=f"LocateAnything CUDA capacity exhausted after adaptive retries: {last_capacity_error}",
            )


service = LocateService()
app = FastAPI(title="LocateAnything Adapter", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


def _decode_b64_image(data: str) -> Image.Image:
    raw = str(data or "").strip()
    if raw.lower().startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(raw, validate=False)
        image = Image.open(BytesIO(image_bytes))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image") from exc
    image = ImageOps.exif_transpose(image)
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _normalize_slug(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _extract_allowed_type_ids(prompt: str) -> list[str]:
    match = re.search(r"Allowed type_id:\s*([^\n\r]+)", prompt)
    if match:
        return [item.strip() for item in re.split(r"[,，\s]+", match.group(1)) if item.strip()]
    ids = re.findall(r"type_id=([A-Za-z0-9_\-]+)", prompt)
    return list(dict.fromkeys(ids))


def _description_for_type_id(prompt: str, type_id: str) -> str:
    escaped = re.escape(type_id)
    parts: list[str] = []
    name_match = re.search(rf"type_id={escaped};\s*name=([^\n\r]+)", prompt)
    if name_match:
        parts.append(name_match.group(1).strip())
    block_match = re.search(
        rf"type_id={escaped};.*?(?=\n-\s*type_id=|\nIf none,|\Z)",
        prompt,
        flags=re.S,
    )
    if block_match:
        for line in block_match.group(0).splitlines():
            line = line.strip()
            if "Check:" in line:
                parts.append(line.split("Check:", 1)[1].strip())
            elif line.startswith("Exclude:"):
                parts.append(f"Exclude: {line.split(':', 1)[1].strip()}")
    if not parts:
        parts.append(type_id.replace("_", " "))
    return "; ".join(dict.fromkeys(part for part in parts if part))


def _chat_prompt_for(prompt: str, allowed_ids: list[str]) -> tuple[str, str]:
    normalized_ids = {_normalize_slug(item) for item in allowed_ids}
    text = prompt.lower()
    if "signature" in normalized_ids or "signature" in text or "签" in prompt:
        return "signature", CUSTOM_VISUAL_PROMPTS["signature"]
    type_id = allowed_ids[0] if allowed_ids else "object"
    description = _description_for_type_id(prompt, type_id)
    return type_id, f"Locate all the instances that match the following description: {description}."


def _box_to_1000(box: dict[str, Any], width: int, height: int) -> list[int]:
    x1 = float(box["x"])
    y1 = float(box["y"])
    x2 = x1 + float(box["width"])
    y2 = y1 + float(box["height"])
    return [
        max(0, min(1000, round(x1 / max(1, width) * 1000))),
        max(0, min(1000, round(y1 / max(1, height) * 1000))),
        max(0, min(1000, round(x2 / max(1, width) * 1000))),
        max(0, min(1000, round(y2 / max(1, height) * 1000))),
    ]


def _find_first_user_image_and_text(messages: list[dict[str, Any]]) -> tuple[Image.Image, str]:
    prompt_parts: list[str] = []
    image: Image.Image | None = None
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            prompt_parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                prompt_parts.append(str(item.get("text") or ""))
            elif item.get("type") == "image_url" and image is None:
                image_url = item.get("image_url") or {}
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                image = _decode_b64_image(str(url or ""))
    if image is None:
        raise HTTPException(status_code=400, detail="No image_url found in messages")
    return image, "\n".join(part for part in prompt_parts if part)


def _detect_prompt(categories: list[str]) -> str:
    prompts = []
    for raw in categories:
        slug = _normalize_slug(raw)
        desc = FIXED_VISUAL_PROMPTS.get(slug, slug.replace("_", " "))
        prompts.append(f"{slug}: {desc}")
    return (
        "Locate all the instances that match the following descriptions. "
        "For every returned box, put the exact category slug before the box, for example "
        "<ref>signature</ref><box><x1><y1><x2><y2></box>. "
        "Use tight boxes around the visible object. Do not return a whole document/page box "
        "unless the category is itself a page-scale document, card, screen, label, receipt, or paper. "
        "If an object is not clearly visible, omit it. "
        f"Descriptions: {'</c>'.join(prompts)}."
    )


def _detect_prompt_for_signature() -> str:
    return CUSTOM_VISUAL_PROMPTS["signature"]


def _box_to_normalized(box: dict[str, Any], width: int, height: int, category: str) -> dict[str, Any] | None:
    x = max(0.0, min(1.0, float(box["x"]) / max(1, width)))
    y = max(0.0, min(1.0, float(box["y"]) / max(1, height)))
    w = max(0.0, min(1.0 - x, float(box["width"]) / max(1, width)))
    h = max(0.0, min(1.0 - y, float(box["height"]) / max(1, height)))
    if not _accept_normalized_box(category, x, y, w, h):
        return None
    return {"x": x, "y": y, "width": w, "height": h, "category": category, "confidence": 0.82}


def _accept_category_pixels(image: Image.Image, box: dict[str, Any], category: str) -> bool:
    return True


def _accept_normalized_box(category: str, x: float, y: float, w: float, h: float) -> bool:
    if w <= 0 or h <= 0:
        return False
    area = w * h
    slug = _normalize_slug(category)
    if slug == "paper":
        return area >= 0.05 and w >= 0.2 and h >= 0.2
    if w < 0.004 or h < 0.004 or area < 0.000025:
        return False
    if slug not in PAGE_SCALE_CATEGORIES and area >= 0.50 and w >= 0.65 and h >= 0.65:
        return False
    if slug == "face":
        aspect = w / max(h, 1e-6)
        return 0.35 <= aspect <= 2.5 and area <= 0.35
    if slug == "signature":
        aspect = w / max(h, 1e-6)
        # Signatures are small handwritten strokes. This removes page-wide lines,
        # blank signing rows, and whole signing areas without relying on page layout.
        return (
            0.012 <= w <= 0.38
            and 0.008 <= h <= 0.16
            and 0.00012 <= area <= 0.035
            and 0.6 <= aspect <= 16.0
        )
    return area <= 0.85


def _box_iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["width"]), ay1 + float(a["height"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["width"]), by1 + float(b["height"])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _box_containment(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["width"]), ay1 + float(a["height"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["width"]), by1 + float(b["height"])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    min_area = min(
        max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1),
        max(0.0, bx2 - bx1) * max(0.0, by2 - by1),
    )
    return inter / min_area if min_area > 0 else 0.0


def _dedupe_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for box in boxes:
        grouped.setdefault(_normalize_slug(box.get("category")), []).append(box)

    kept_all: list[dict[str, Any]] = []
    for category, items in grouped.items():
        prefer_large = category == "paper"
        ordered = sorted(
            items,
            key=lambda item: float(item["width"]) * float(item["height"]),
            reverse=prefer_large,
        )
        kept: list[dict[str, Any]] = []
        for item in ordered:
            if any(_box_iou(item, existing) >= 0.55 or _box_containment(item, existing) >= 0.78 for existing in kept):
                continue
            kept.append(item)
        kept_all.extend(kept)
    return sorted(kept_all, key=lambda item: (item.get("category", ""), float(item["y"]), float(item["x"])))


def _signature_tile_specs(width: int, height: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    if width < 640 or height < 640 or SIGNATURE_TILE_FALLBACK_MAX_TILES <= 0:
        return []
    raw_specs = [
        ("bottom_half", (0, height // 2, width, height)),
        ("top_half", (0, 0, width, max(1, (height + 1) // 2))),
        ("middle_band", (0, int(height * 0.25), width, max(1, int(height * 0.75)))),
        ("bottom_third", (0, int(height * 0.62), width, height)),
    ]
    specs: list[tuple[str, tuple[int, int, int, int]]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for name, (left, top, right, bottom) in raw_specs:
        left = max(0, min(width - 1, int(left)))
        top = max(0, min(height - 1, int(top)))
        right = max(left + 1, min(width, int(right)))
        bottom = max(top + 1, min(height, int(bottom)))
        box = (left, top, right, bottom)
        if box in seen:
            continue
        seen.add(box)
        specs.append((name, box))
        if len(specs) >= SIGNATURE_TILE_FALLBACK_MAX_TILES:
            break
    return specs


async def _predict_signature_boxes_with_fallback(
    image: Image.Image,
    *,
    generation_mode: str | None = None,
    fast_first: bool | None = None,
    use_fallback: bool = True,
    max_image_side: int | None = None,
) -> tuple[str, list[dict[str, Any]], tuple[int, int]]:
    prompt = _detect_prompt_for_signature()
    requested_mode = _normalize_generation_mode(generation_mode or "fast")
    signature_max_side = max(640, int(max_image_side or SIGNATURE_MAX_SIDE))
    answer, boxes, (width, height) = await service.predict_boxes(
        image,
        prompt,
        max_image_side=signature_max_side,
        generation_mode=requested_mode,
        temperature=0.1,
        fast_first=fast_first,
        fallback_when_no_boxes=bool(use_fallback),
    )
    accepted = [
        box
        for box in boxes
        if _box_to_normalized(box, width, height, "signature") is not None
    ]
    if accepted or not use_fallback:
        return answer, accepted, (width, height)

    raw_answers = [f"[full-{requested_mode}] {answer}"]
    fallback_mode = _normalize_generation_mode(DEFAULT_GENERATION_MODE)
    if fallback_mode != requested_mode:
        fallback_answer, fallback_boxes, _ = await service.predict_boxes(
            image,
            prompt,
            max_image_side=signature_max_side,
            generation_mode=fallback_mode,
            temperature=0.1,
            fast_first=False,
        )
        raw_answers.append(f"[full-{fallback_mode}] {fallback_answer}")
        fallback_accepted = [
            box
            for box in fallback_boxes
            if _box_to_normalized(box, width, height, "signature") is not None
        ]
        if fallback_accepted:
            return "\n".join(raw_answers), fallback_accepted, (width, height)

    mapped: list[dict[str, Any]] = []
    tile_max_side = min(signature_max_side, SIGNATURE_TILE_FALLBACK_MAX_SIDE)
    for tile_name, (left, top, right, bottom) in _signature_tile_specs(width, height):
        crop = image.crop((left, top, right, bottom))
        tile_answer, tile_boxes, _tile_size = await service.predict_boxes(
            crop,
            prompt,
            max_image_side=tile_max_side,
            generation_mode=requested_mode,
            temperature=0.1,
            fast_first=False,
            fallback_when_no_boxes=False,
        )
        raw_answers.append(f"[{tile_name}] {tile_answer}")
        for box in tile_boxes:
            mapped_box = {
                **box,
                "x": round(float(box["x"]) + left, 2),
                "y": round(float(box["y"]) + top, 2),
            }
            if _box_to_normalized(mapped_box, width, height, "signature") is not None:
                mapped.append(mapped_box)

    return "\n".join(raw_answers), mapped, (width, height)


def _category_from_label(label: str, categories: list[str]) -> str | None:
    if len(categories) == 1:
        return categories[0]
    text = _normalize_slug(label)
    for category in categories:
        slug = _normalize_slug(category)
        if slug and slug in text:
            return slug
    keyword_map = {
        "official_seal": ("seal", "stamp", "red_stamp", "red_seal"),
        "qr_code": ("qr", "qrcode"),
        "barcode": ("bar_code", "barcode"),
        "id_card": ("identity", "national_id"),
        "bank_card": ("credit_card", "bank_card"),
        "face": ("face", "human_face"),
        "fingerprint": ("fingerprint", "finger_print"),
        "palmprint": ("palmprint", "palm_print"),
        "hk_macau_permit": ("hong_kong", "macau", "permit"),
        "passport": ("passport",),
        "employee_badge": ("employee", "badge", "work_id"),
        "license_plate": ("license_plate", "plate"),
        "physical_key": ("key",),
        "receipt": ("receipt",),
        "shipping_label": ("shipping", "delivery", "waybill"),
        "whiteboard": ("whiteboard",),
        "sticky_note": ("sticky", "note"),
        "mobile_screen": ("mobile", "phone_screen"),
        "monitor_screen": ("monitor", "computer_screen"),
        "medical_wristband": ("wristband",),
        "paper": ("paper", "document_page", "page"),
        "signature": ("signature", "signer", "handwritten"),
    }
    for category in categories:
        for keyword in keyword_map.get(_normalize_slug(category), ()):
            if keyword in text:
                return _normalize_slug(category)
    return None


@app.on_event("startup")
async def startup() -> None:
    print(f"[LocateAnything] loading model={service.model_path}", flush=True)
    await asyncio.to_thread(service.load)
    print("[LocateAnything] ready", flush=True)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok" if service.ready else "loading",
        "ready": service.ready,
        "model": MODEL_NAME,
        "runtime": "transformers-locateanything",
        "runtime_mode": "gpu",
        "gpu_available": True,
        "gpu_only_mode": True,
        "cpu_fallback_risk": False,
        "max_image_side": DEFAULT_MAX_SIDE,
    }


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest) -> dict[str, Any]:
    if req.stream:
        raise HTTPException(status_code=400, detail="stream=true is not supported")
    image, prompt = _find_first_user_image_and_text(req.messages)
    allowed_ids = _extract_allowed_type_ids(prompt)
    type_id, locate_prompt = _chat_prompt_for(prompt, allowed_ids)
    max_new_tokens = max(int(req.max_tokens or 0), DEFAULT_MAX_NEW_TOKENS)
    temperature = float(req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE)
    if type_id == "signature":
        answer, boxes, (width, height) = await _predict_signature_boxes_with_fallback(image)
    else:
        answer, boxes, (width, height) = await service.predict_boxes(
            image,
            locate_prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
    wants_json = "Schema:" in prompt or "Allowed type_id:" in prompt or '"objects"' in prompt
    if wants_json:
        normalized_objects: list[dict[str, Any]] = []
        for box in boxes:
            normalized = _box_to_normalized(box, width, height, type_id)
            if normalized is not None and _accept_category_pixels(image, box, type_id):
                normalized_objects.append(normalized)
        normalized_objects = _dedupe_boxes(normalized_objects)
        objects = [
            {
                "type_id": type_id,
                "label": type_id,
                "box_2d": [
                    max(0, min(1000, round(float(box["x"]) * 1000))),
                    max(0, min(1000, round(float(box["y"]) * 1000))),
                    max(0, min(1000, round((float(box["x"]) + float(box["width"])) * 1000))),
                    max(0, min(1000, round((float(box["y"]) + float(box["height"])) * 1000))),
                ],
                "confidence": 0.82,
                "rule_matched": f"{type_id}#locateanything",
                "text": str(box.get("label") or type_id),
            }
            for box in normalized_objects
        ]
        content = json.dumps({"objects": objects}, ensure_ascii=False, separators=(",", ":"))
    else:
        content = answer
    return {
        "id": f"chatcmpl-locate-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or MODEL_NAME,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/detect")
async def detect(req: DetectRequest) -> dict[str, Any]:
    image = _decode_b64_image(req.image_base64)
    requested = [_normalize_slug(item) for item in (req.categories or list(FIXED_VISUAL_PROMPTS))]
    requested = [item for item in requested if item in FIXED_VISUAL_PROMPTS]
    if not requested:
        return {"boxes": [], "elapsed": 0.0, "model": MODEL_NAME}
    start = time.perf_counter()
    raw_answers: list[str] = []
    out: list[dict[str, Any]] = []
    signature_requested = "signature" in requested
    general_requested = [item for item in requested if item != "signature"]

    if general_requested:
        prompt = _detect_prompt(general_requested)
        answer, boxes, (width, height) = await service.predict_boxes(image, prompt)
        raw_answers.append(answer)
        for box in boxes:
            category = _category_from_label(str(box.get("label") or ""), general_requested)
            if category is None:
                continue
            normalized = _box_to_normalized(box, width, height, category)
            if normalized is not None and _accept_category_pixels(image, box, category):
                out.append(normalized)

    if signature_requested:
        answer, boxes, (width, height) = await _predict_signature_boxes_with_fallback(
            image,
            generation_mode=req.generation_mode,
            fast_first=req.fast_first,
            use_fallback=req.signature_fallback,
            max_image_side=req.max_image_side,
        )
        raw_answers.append(answer)
        for box in boxes:
            normalized = _box_to_normalized(box, width, height, "signature")
            if normalized is not None:
                out.append(normalized)

    out = _dedupe_boxes(out)
    elapsed = time.perf_counter() - start
    print(f"[LocateAnything] detect categories={requested} boxes={len(out)} elapsed={elapsed:.2f}s", flush=True)
    return {"boxes": out, "elapsed": elapsed, "model": MODEL_NAME, "raw_answer": "\n".join(raw_answers)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("LOCATE_ANYTHING_MODEL", "/mnt/d/has_models/LocateAnything-3B-HF"))
    parser.add_argument("--backend", choices=["auto", "modelscope", "hf"], default=os.environ.get("LOCATE_ANYTHING_BACKEND", "hf"))
    parser.add_argument("--dtype", choices=["bfloat16", "float16", "float32"], default=os.environ.get("LOCATE_ANYTHING_DTYPE", "bfloat16"))
    parser.add_argument("--host", default=os.environ.get("LOCATE_ANYTHING_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("LOCATE_ANYTHING_PORT", "8090")))
    args = parser.parse_args()

    service.configure(args.model, args.backend, args.dtype)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
