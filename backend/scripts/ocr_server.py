"""PaddleOCR-VL 1.6 sidecar service on port 8082."""

from __future__ import annotations

import asyncio
import base64
import gc
import math
import os
import tempfile
import time
from collections.abc import Iterable
from io import BytesIO
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, Field

app = FastAPI(title="PaddleOCR-VL Service", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

_vl: Any | None = None
_ocr: Any | None = None
_structure: Any | None = None
_ready = False
_model_name = "PaddleOCR-VL-1.6-0.9B"
_paddle_device = ""

# Serializes all Paddle inference (predictors are not thread-safe) while the
# event loop stays free: endpoints run inference via asyncio.to_thread inside
# this lock, so /health keeps responding during long predictions. The lock must
# wrap EVERY Paddle inference call site; /health must never take it.
_infer_lock = asyncio.Lock()

MAX_SIDE = int(os.environ.get("OCR_MAX_IMAGE_SIDE", "1600"))
SEAL_TEXT = "[公章]"

DEFAULT_CONFIDENCE = 0.9  # fallback confidence score when a box has none
MAX_ITER_DEPTH = 8  # max recursion depth when walking nested OCR result objects
NORMALIZED_COORD_MAX = 1.5  # if all coords <= this, treat them as already in [0,1] space
MIN_BOX_SIZE = 1.0  # floor (px) for a box's width/height after clamping
DEDUP_ROUND_DIGITS = 4  # rounding precision for the box dedup key
SEAL_PAD_MIN = 4.0  # min padding (px) added around a stitched seal bbox
SEAL_PAD_RATIO = 0.01  # padding as a fraction of the image's shorter side


class OCRRequest(BaseModel):
    image: str = Field(..., description="Base64 image data")
    max_new_tokens: int = Field(default=512, ge=1, le=8192)


class StructureRequest(BaseModel):
    image: str = Field(..., description="Base64 image data")
    use_ocr_results_with_table_cells: bool = True
    use_e2e_wired_table_rec_model: bool = False
    use_e2e_wireless_table_rec_model: bool = False
    use_wired_table_cells_trans_to_html: bool = False
    use_wireless_table_cells_trans_to_html: bool = False
    use_table_orientation_classify: bool = True


class OCRBox(BaseModel):
    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = DEFAULT_CONFIDENCE
    label: str = "text"
    # Per-character boxes (normalized) for this line, left-to-right. Lets the
    # backend redact the exact pixels of an entity instead of estimating a
    # sub-span or masking the whole block.
    chars: list[dict[str, Any]] = []


class OCRResponse(BaseModel):
    boxes: list[OCRBox]
    model: str
    elapsed: float


def _fatal(exit_code: int = 1) -> None:
    os._exit(exit_code)


def _allow_cpu() -> bool:
    return os.environ.get("OCR_ALLOW_CPU", "").strip().lower() in {"1", "true", "yes", "on"}


def _structure_enabled() -> bool:
    return os.environ.get("OCR_STRUCTURE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _require_gpu_or_exit() -> None:
    global _paddle_device
    try:
        import paddle
    except ImportError as exc:
        print(f"[OCR] FATAL: paddle is not installed: {exc}", flush=True)
        _fatal(1)

    if _allow_cpu():
        print("[OCR] WARN: OCR_ALLOW_CPU is enabled; GPU remains preferred.", flush=True)
        try:
            if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                paddle.set_device("gpu:0")
                _paddle_device = str(paddle.get_device())
            else:
                paddle.set_device("cpu")
                _paddle_device = "cpu"
        except Exception as exc:
            print(f"[OCR] WARN: failed to select Paddle device: {exc}", flush=True)
        return

    if not paddle.is_compiled_with_cuda():
        print("[OCR] FATAL: installed Paddle build has no CUDA support.", flush=True)
        _fatal(1)

    try:
        gpu_count = paddle.device.cuda.device_count()
    except Exception as exc:
        print(f"[OCR] FATAL: failed to enumerate CUDA devices: {exc}", flush=True)
        _fatal(1)

    if gpu_count < 1:
        print("[OCR] FATAL: no CUDA device is visible to Paddle.", flush=True)
        _fatal(1)

    try:
        paddle.set_device("gpu:0")
        _paddle_device = str(paddle.get_device())
        print(f"[OCR] Paddle GPU ready: device={_paddle_device}, visible_gpus={gpu_count}", flush=True)
    except Exception as exc:
        print(f"[OCR] FATAL: failed to select Paddle GPU: {exc}", flush=True)
        _fatal(1)


def trim_cuda_cache(label: str) -> None:
    try:
        gc.collect()
    except Exception:
        pass
    try:
        import paddle

        paddle.device.cuda.empty_cache()
        print(f"[OCR] CUDA cache trimmed after {label}", flush=True)
    except Exception:
        pass


def _vl_disabled() -> bool:
    return str(os.environ.get("OCR_VL_ENABLED", "1")).strip().lower() in {"0", "false", "no", "off"}


def init_ocr() -> None:
    global _vl, _ocr, _ready, _model_name
    _require_gpu_or_exit()

    if _vl_disabled():
        # Structure-only mode: PP-StructureV3 is the primary OCR path, so the
        # heavy PaddleOCR-VL model is not loaded at all (frees GPU memory for
        # HaS / LocateAnything). The /ocr (VL) endpoint returns 503; /structure works.
        _vl = None
        _ready = True
        _model_name = "PP-StructureV3 (PaddleOCR-VL disabled)"
        print("[OCR] PaddleOCR-VL disabled (OCR_VL_ENABLED=0); PP-StructureV3-only mode", flush=True)
        return

    try:
        from paddleocr import PaddleOCRVL

        vl_backend = os.environ.get("OCR_VL_BACKEND", "").strip()
        if vl_backend:
            vl_server_url = os.environ.get("OCR_VLLM_URL", "http://127.0.0.1:8118/v1").strip()
            vl_model_name = os.environ.get("OCR_VL_API_MODEL_NAME", "PaddleOCR-VL-1.6-0.9B").strip()
            _vl = PaddleOCRVL(
                pipeline_version="v1.6",
                vl_rec_backend=vl_backend,
                vl_rec_server_url=vl_server_url,
                vl_rec_api_model_name=vl_model_name,
            )
            _model_name = f"PaddleOCR-VL via {vl_backend} ({vl_model_name})"
        else:
            _vl = PaddleOCRVL(pipeline_version="v1.6")
            _model_name = "PaddleOCR-VL-1.6-0.9B"
        _ready = True
        print(f"[OCR] {_model_name} loaded on {_paddle_device or 'device'}", flush=True)
        warmup()
        return
    except Exception as exc:
        print(f"[OCR] FATAL: PaddleOCR-VL init failed: {exc}", flush=True)
        if not _allow_cpu():
            _fatal(1)
        _vl = None

    try:
        from paddleocr import PaddleOCR

        _ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        _ready = True
        _model_name = "PaddleOCR-2.x CPU fallback"
        print(f"[OCR] {_model_name} loaded because OCR_ALLOW_CPU is enabled", flush=True)
    except Exception as exc:
        print(f"[OCR] FATAL: fallback PaddleOCR init failed: {exc}", flush=True)
        _ready = False


def warmup() -> None:
    if not _vl:
        return
    try:
        print("[OCR] Warming up PaddleOCR-VL...", flush=True)
        image = Image.new("RGB", (300, 200), color="white")
        draw = ImageDraw.Draw(image)
        draw.text((50, 80), "Warmup Test", fill="black")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
            temp_path = file.name
            image.save(file, format="PNG")
        try:
            _vl.predict(temp_path, max_new_tokens=256)
        finally:
            _remove_file(temp_path)
        print("[OCR] PaddleOCR-VL warmup complete", flush=True)
    except Exception as exc:
        print(f"[OCR] PaddleOCR-VL warmup failed: {exc}", flush=True)


def warmup_structure() -> None:
    if not _structure_enabled():
        print("[OCR] PP-StructureV3 disabled", flush=True)
        return
    if os.environ.get("OCR_STRUCTURE_WARMUP", "1").strip().lower() in {"0", "false", "no", "off"}:
        print("[OCR] PP-StructureV3 warmup skipped", flush=True)
        return
    try:
        print("[OCR] Warming up PP-StructureV3...", flush=True)
        image = Image.new("RGB", (480, 320), color="white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 60, 440, 260), outline="black", width=2)
        draw.line((40, 140, 440, 140), fill="black", width=1)
        draw.line((240, 60, 240, 260), fill="black", width=1)
        draw.text((70, 92), "Name", fill="black")
        draw.text((270, 92), "Value", fill="black")
        extract_structure(image, StructureRequest(image=""))
        trim_cuda_cache("structure warmup")
        print("[OCR] PP-StructureV3 warmup complete", flush=True)
    except Exception as exc:
        print(f"[OCR] PP-StructureV3 warmup failed: {exc}", flush=True)


def get_structure_engine() -> Any | None:
    global _structure, _model_name
    if not _structure_enabled():
        return None
    if _structure is not None:
        return _structure
    try:
        from paddleocr import PPStructureV3

        _structure = PPStructureV3(
            use_table_recognition=True,
            use_seal_recognition=False,  # 公章由 LocateAnything 负责；关掉避免印章曲文被去扭曲后堆到左上角伪坐标
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=True,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_limit_type="min",
            text_det_limit_side_len=736,
            text_det_thresh=0.30,
            text_det_box_thresh=0.60,
            text_det_unclip_ratio=1.5,
            text_rec_score_thresh=0.0,
        )
        _model_name = "PaddleOCR-VL-1.6-0.9B + PP-StructureV3" if _vl is not None else "PP-StructureV3"
        print("[OCR] PP-StructureV3 loaded", flush=True)
        return _structure
    except Exception as exc:
        print(f"[OCR] PP-StructureV3 init failed: {exc}", flush=True)
        return None


def release_structure_engine_if_configured() -> None:
    if os.environ.get("OCR_STRUCTURE_RELEASE_AFTER_REQUEST", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    global _structure, _model_name
    if _structure is None:
        return
    _structure = None
    _model_name = "PaddleOCR-VL-1.6-0.9B"
    trim_cuda_cache("structure release")
    print("[OCR] PP-StructureV3 released after request", flush=True)


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


def _box_from_poly(poly: Any) -> list[float] | None:
    try:
        if poly is None:
            return None
        if len(poly) == 4 and all(isinstance(value, (int, float)) for value in poly):
            x1, y1, x2, y2 = [float(value) for value in poly]
            return [x1, y1, x2, y2]
        xs = [float(point[0]) for point in poly]
        ys = [float(point[1]) for point in poly]
        return [min(xs), min(ys), max(xs), max(ys)]
    except Exception:
        return None


def _first_value(mapping: dict, *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _has_items(value: Any) -> bool:
    try:
        return value is not None and len(value) > 0
    except TypeError:
        return value is not None


def _iter_dicts(obj: Any, depth: int = 0) -> Iterable[dict]:
    if depth > MAX_ITER_DEPTH or obj is None:
        return
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value, depth + 1)
        return
    if isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _iter_dicts(value, depth + 1)
        return
    for attr in (
        "overall_ocr_res",
        "layout_det_res",
        "region_det_res",
        "table_res_list",
        "seal_res_list",
        "parsing_res_list",
        "layout_parsing_result",
        "markdown",
    ):
        if hasattr(obj, attr):
            yield from _iter_dicts(getattr(obj, attr), depth + 1)
    if hasattr(obj, "__getitem__"):
        for key in (
            "overall_ocr_res",
            "table_res_list",
            "parsing_res_list",
            "layout_parsing_result",
            "layout_det_res",
            "region_det_res",
            "seal_res_list",
            "rec_texts",
            "rec_polys",
            "rec_boxes",
        ):
            try:
                yield from _iter_dicts(obj[key], depth + 1)
            except Exception:
                pass


def _append_raw_box(raw: list[dict], text: str, box: Any, label: str, confidence: float = DEFAULT_CONFIDENCE) -> None:
    content = str(text or "").strip()
    if not content:
        return
    bbox = _box_from_poly(box)
    if not bbox:
        return
    x1, y1, x2, y2 = bbox
    if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
        return
    if x2 <= x1 or y2 <= y1:
        return
    raw.append({"text": content, "box": [x1, y1, x2, y2], "confidence": confidence, "label": label})


def _normalize_boxes(raw_boxes: list[dict], width: int, height: int) -> list[OCRBox]:
    if not raw_boxes:
        return []
    raw_boxes = [
        box
        for box in raw_boxes
        if len(box.get("box", [])) == 4 and all(math.isfinite(float(value)) for value in box["box"])
    ]
    if not raw_boxes:
        return []

    max_x = max(float(box["box"][2]) for box in raw_boxes)
    max_y = max(float(box["box"][3]) for box in raw_boxes)
    if max(max_x, max_y) <= NORMALIZED_COORD_MAX:
        space_w, space_h = 1.0, 1.0
    else:
        space_w, space_h = float(width), float(height)

    seen: set[tuple] = set()
    items: list[OCRBox] = []
    for raw in raw_boxes:
        x1, y1, x2, y2 = [float(value) for value in raw["box"]]
        x1 = x1 / space_w * width
        y1 = y1 / space_h * height
        x2 = x2 / space_w * width
        y2 = y2 / space_h * height
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        x1 = max(0.0, min(x1, float(width)))
        x2 = max(0.0, min(x2, float(width)))
        y1 = max(0.0, min(y1, float(height)))
        y2 = max(0.0, min(y2, float(height)))
        w = max(MIN_BOX_SIZE, x2 - x1)
        h = max(MIN_BOX_SIZE, y2 - y1)
        key = (
            raw["text"],
            round(x1 / width, DEDUP_ROUND_DIGITS),
            round(y1 / height, DEDUP_ROUND_DIGITS),
            round(w / width, DEDUP_ROUND_DIGITS),
            round(h / height, DEDUP_ROUND_DIGITS),
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(
            OCRBox(
                text=raw["text"],
                x=x1 / width,
                y=y1 / height,
                width=w / width,
                height=h / height,
                confidence=float(raw.get("confidence", DEFAULT_CONFIDENCE) or DEFAULT_CONFIDENCE),
                label=str(raw.get("label") or "text"),
            )
        )
    return items


def map_boxes_to_original(items: list[OCRBox]) -> list[OCRBox]:
    mapped: list[OCRBox] = []
    for item in items:
        mapped.append(
            OCRBox(
                text=item.text,
                x=max(0.0, min(float(item.x), 1.0)),
                y=max(0.0, min(float(item.y), 1.0)),
                width=max(0.0, min(float(item.width), 1.0)),
                height=max(0.0, min(float(item.height), 1.0)),
                confidence=item.confidence,
                label=item.label,
                chars=item.chars,
            )
        )
    return mapped


def _extract_vl_parsing_boxes(outputs: Any) -> list[dict]:
    raw: list[dict] = []
    if not outputs:
        return raw
    for result in outputs:
        parsing_list = None
        if hasattr(result, "parsing_res_list"):
            parsing_list = result.parsing_res_list
        elif hasattr(result, "__getitem__"):
            try:
                parsing_list = result["parsing_res_list"]
            except Exception:
                parsing_list = None
        for block in parsing_list or []:
            if isinstance(block, dict):
                label = block.get("block_label") or block.get("label") or ""
                content = block.get("block_content") or block.get("content") or ""
                box = block.get("block_bbox") or block.get("bbox")
            else:
                label = getattr(block, "label", "") or getattr(block, "block_label", "")
                content = getattr(block, "content", "") or getattr(block, "block_content", "")
                box = getattr(block, "bbox", None) or getattr(block, "block_bbox", None)
            label = str(label or "").strip().lower()
            if label == "seal":
                content = SEAL_TEXT
            if box is None or len(box) != 4:
                continue
            if not content and label != "seal":
                continue
            _append_raw_box(raw, str(content or SEAL_TEXT), box, label or "text", DEFAULT_CONFIDENCE)
    return raw


def _extract_vl_spotting_boxes(outputs: Any) -> list[dict]:
    raw: list[dict] = []
    if not outputs:
        return raw
    for result in outputs:
        spotting = None
        if hasattr(result, "__getitem__"):
            try:
                spotting = result["spotting_res"]
            except Exception:
                spotting = None
        if not spotting and hasattr(result, "spotting_res"):
            spotting = getattr(result, "spotting_res", None)
        if not spotting:
            continue
        for poly, text in zip(spotting.get("rec_polys", []) or [], spotting.get("rec_texts", []) or [], strict=False):
            _append_raw_box(raw, str(text or "").strip(), poly, "spotting", DEFAULT_CONFIDENCE)
    return raw


def extract_vl(image: Image.Image, max_new_tokens: int = 512) -> list[OCRBox]:
    if not _vl:
        return []

    width, height = image.size
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
        temp_path = file.name
        image.save(file, format="PNG")

    try:
        raw_boxes: list[dict] = []
        try:
            outputs = _vl.predict(temp_path, max_new_tokens=max_new_tokens)
            raw_boxes = _extract_vl_parsing_boxes(outputs)
            print(f"[OCR] PaddleOCR-VL parser produced {len(raw_boxes)} boxes", flush=True)
        except Exception as exc:
            print(f"[OCR] PaddleOCR-VL parser failed: {exc}", flush=True)

        if not raw_boxes:
            outputs = _vl.predict(
                temp_path,
                use_layout_detection=False,
                prompt_label="spotting",
                max_new_tokens=max_new_tokens,
            )
            raw_boxes = _extract_vl_spotting_boxes(outputs)
            print(f"[OCR] PaddleOCR-VL spotting produced {len(raw_boxes)} boxes", flush=True)
    except Exception as exc:
        print(f"[OCR] PaddleOCR-VL predict failed: {exc}", flush=True)
        return []
    finally:
        _remove_file(temp_path)

    return _normalize_boxes(raw_boxes, width, height)


def _collect_structure_raw(outputs: Any, width: int, height: int) -> list[dict]:
    raw: list[dict] = []
    for item in _iter_dicts(outputs):
        layout_boxes = _first_value(item, "boxes")
        if isinstance(layout_boxes, list) and layout_boxes and all(isinstance(entry, dict) for entry in layout_boxes):
            for box_info in layout_boxes:
                label = str(_first_value(box_info, "label", "block_label") or "").strip().lower()
                if label != "seal":
                    continue
                coord = _first_value(box_info, "coordinate", "bbox", "box", "dt_polys", "rec_box")
                _append_raw_box(raw, SEAL_TEXT, coord, "seal", float(_first_value(box_info, "score", "confidence") or DEFAULT_CONFIDENCE))

        seal_items = _first_value(item, "seal_res_list")
        if isinstance(seal_items, list):
            for seal in seal_items:
                if not isinstance(seal, dict):
                    continue
                outer = _first_value(seal, "coordinate", "bbox", "box", "seal_bbox", "dt_polys", "rec_box")
                if outer:
                    _append_raw_box(raw, SEAL_TEXT, outer, "seal", float(_first_value(seal, "score", "confidence") or DEFAULT_CONFIDENCE))
                    continue
                seal_polys = _first_value(seal, "rec_polys", "dt_polys", "rec_boxes", "dt_boxes", "boxes")
                if _has_items(seal_polys):
                    parts = [_box_from_poly(poly) for poly in seal_polys]
                    parts = [part for part in parts if part]
                    if parts:
                        x1 = min(part[0] for part in parts)
                        y1 = min(part[1] for part in parts)
                        x2 = max(part[2] for part in parts)
                        y2 = max(part[3] for part in parts)
                        pad = max(SEAL_PAD_MIN, min(width, height) * SEAL_PAD_RATIO)
                        _append_raw_box(raw, SEAL_TEXT, [x1 - pad, y1 - pad, x2 + pad, y2 + pad], "seal")

        texts = _first_value(item, "rec_texts", "texts", "ocr_texts")
        polys = _first_value(item, "rec_polys", "dt_polys", "polys")
        boxes = _first_value(item, "rec_boxes", "dt_boxes", "boxes")
        if _has_items(texts) and (_has_items(polys) or _has_items(boxes)):
            coords = polys if _has_items(polys) else boxes
            for text, box in zip(texts, coords, strict=False):
                _append_raw_box(raw, str(text or ""), box, "structure")

        cells = _first_value(item, "cell_box_list", "cell_boxes")
        cell_texts = _first_value(item, "cell_texts", "table_cells_texts")
        if _has_items(cells) and _has_items(cell_texts):
            for text, box in zip(cell_texts, cells, strict=False):
                _append_raw_box(raw, str(text or ""), box, "table_cell")

        content = _first_value(item, "block_content", "content", "text")
        bbox = _first_value(item, "block_bbox", "bbox")
        label = str(_first_value(item, "block_label", "label") or "structure")
        if content and _has_items(bbox):
            _append_raw_box(raw, str(content), bbox, label)
    return raw


_word_engine: Any = None
_word_engine_failed = False


def get_word_engine() -> Any | None:
    """Lazy PaddleOCR with per-character boxes (return_word_box). Mobile det/rec
    keep the extra GPU cost tiny (~0.3 GB). Init is attempted once: a failure
    sets a sentinel so every later request does not retry the heavy init."""
    global _word_engine, _word_engine_failed
    if _word_engine is not None:
        return _word_engine
    if _word_engine_failed:
        return None
    try:
        from paddleocr import PaddleOCR

        _word_engine = PaddleOCR(
            return_word_box=True,
            use_textline_orientation=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
        )
        print("[OCR] word-box engine loaded", flush=True)
    except Exception as exc:
        print(f"[OCR] word-box engine init failed (will not retry): {exc}", flush=True)
        _word_engine = None
        _word_engine_failed = True
    return _word_engine


def _char_box_xyxy(box: Any) -> tuple[float, float, float, float]:
    import numpy as np

    arr = np.asarray(box, dtype=float)
    if arr.ndim == 1 and arr.size == 4:
        x1, y1, x2, y2 = arr.tolist()
    else:
        pts = arr.reshape(-1, 2)
        x1, y1 = float(pts[:, 0].min()), float(pts[:, 1].min())
        x2, y2 = float(pts[:, 0].max()), float(pts[:, 1].max())
    return float(x1), float(y1), float(x2), float(y2)


def _extract_char_boxes(image: Image.Image) -> list[dict[str, Any]]:
    engine = get_word_engine()
    if engine is None:
        return []
    width, height = image.size
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
        temp_path = file.name
        image.save(file, format="PNG")
    chars: list[dict[str, Any]] = []
    try:
        for result in engine.predict(temp_path):
            try:
                line_chars = result["text_word"]
                line_boxes = result["text_word_boxes"]
            except (KeyError, TypeError):
                continue
            for words, boxes in zip(line_chars, line_boxes, strict=False):
                for ch, box in zip(words, boxes, strict=False):
                    x1, y1, x2, y2 = _char_box_xyxy(box)
                    if x2 <= x1 or y2 <= y1:
                        continue
                    chars.append({
                        "c": str(ch),
                        "x": x1 / width,
                        "y": y1 / height,
                        "w": (x2 - x1) / width,
                        "h": (y2 - y1) / height,
                    })
    except Exception as exc:
        print(f"[OCR] char-box extraction failed: {exc}", flush=True)
    finally:
        _remove_file(temp_path)
    return chars


def _attach_chars(boxes: list[OCRBox], chars: list[dict[str, Any]]) -> None:
    """Attach to each line box the char boxes whose center falls inside it,
    ordered left-to-right."""
    if not chars:
        return
    for box in boxes:
        bx1, by1 = box.x, box.y
        bx2, by2 = box.x + box.width, box.y + box.height
        inside = [
            ch for ch in chars
            if bx1 <= ch["x"] + ch["w"] / 2 <= bx2 and by1 <= ch["y"] + ch["h"] / 2 <= by2
        ]
        inside.sort(key=lambda c: c["x"])
        box.chars = inside


def extract_structure(image: Image.Image, request: StructureRequest) -> list[OCRBox]:
    engine = get_structure_engine()
    if not engine:
        return []

    width, height = image.size
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as file:
        temp_path = file.name
        image.save(file, format="PNG")

    try:
        outputs = engine.predict(
            temp_path,
            use_table_recognition=True,
            use_seal_recognition=False,  # 公章由 LocateAnything 负责；关掉避免印章曲文被去扭曲后堆到左上角伪坐标
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=True,
            use_ocr_results_with_table_cells=request.use_ocr_results_with_table_cells,
            use_e2e_wired_table_rec_model=request.use_e2e_wired_table_rec_model,
            use_e2e_wireless_table_rec_model=request.use_e2e_wireless_table_rec_model,
            use_wired_table_cells_trans_to_html=request.use_wired_table_cells_trans_to_html,
            use_wireless_table_cells_trans_to_html=request.use_wireless_table_cells_trans_to_html,
            use_table_orientation_classify=request.use_table_orientation_classify,
        )
        raw_boxes = _collect_structure_raw(outputs, width, height)
        print(f"[OCR] PP-StructureV3 produced {len(raw_boxes)} boxes", flush=True)
    except Exception as exc:
        print(f"[OCR] PP-StructureV3 predict failed: {exc}", flush=True)
        return []
    finally:
        _remove_file(temp_path)

    return _normalize_boxes(raw_boxes, width, height)


def prepare_image(image_bytes: bytes) -> tuple[Image.Image, Image.Image, float, float]:
    original = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes)).convert("RGB"))
    orig_w, orig_h = original.size
    max_side = max(orig_w, orig_h)
    if max_side > MAX_SIDE:
        scale = MAX_SIDE / max_side
        ocr_w, ocr_h = max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
        ocr_image = original.resize((ocr_w, ocr_h), Image.Resampling.LANCZOS)
    else:
        ocr_image = original
        ocr_w, ocr_h = orig_w, orig_h
    scale_x = ocr_w / orig_w if orig_w else 1.0
    scale_y = ocr_h / orig_h if orig_h else 1.0
    return original, ocr_image, scale_x, scale_y


@app.get("/health")
async def health() -> dict[str, Any]:
    gpu_ok = False
    device = _paddle_device
    try:
        import paddle

        gpu_ok = bool(paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0)
        if not device:
            device = str(paddle.get_device())
    except Exception:
        pass

    gpu_only_mode = not _allow_cpu()
    runtime_mode = "gpu" if gpu_ok and str(device).lower().startswith("gpu") else "cpu"
    return {
        "status": "online" if _ready else "offline",
        "model": _model_name,
        "ready": _ready,
        "runtime": "paddleocr",
        "runtime_mode": runtime_mode,
        "gpu_available": gpu_ok,
        "device": device or "unknown",
        "gpu_only_mode": gpu_only_mode,
        "cpu_fallback_risk": (not gpu_only_mode) or runtime_mode != "gpu",
        "structure_ready": _structure is not None,
    }


@app.post("/ocr", response_model=OCRResponse)
async def ocr_extract(request: OCRRequest) -> OCRResponse:
    if not _ready:
        raise HTTPException(status_code=503, detail="OCR service is not ready")
    if _vl is None:
        raise HTTPException(status_code=503, detail="PaddleOCR-VL is disabled; use /structure")

    start = time.perf_counter()
    try:
        image_bytes = base64.b64decode(request.image)
        # prepare_image decodes the pixel data; a truncated/corrupt payload that
        # fails there is still a client error (400), not a server fault.
        _original, ocr_image, _scale_x, _scale_y = prepare_image(image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image") from exc

    # Inference runs in a worker thread under the module lock so /health stays
    # responsive while keeping the single-request serial semantics (the Paddle
    # predictor is not thread-safe).
    async with _infer_lock:
        try:
            items = await asyncio.to_thread(extract_vl, ocr_image, request.max_new_tokens)
        finally:
            trim_cuda_cache("ocr")

    mapped = map_boxes_to_original(items)
    elapsed = time.perf_counter() - start
    print(f"[OCR] OCR {len(mapped)} boxes in {elapsed:.2f}s", flush=True)
    return OCRResponse(boxes=mapped, model=_model_name, elapsed=elapsed)


@app.post("/structure", response_model=OCRResponse)
async def structure_extract(request: StructureRequest) -> OCRResponse:
    if not _ready:
        raise HTTPException(status_code=503, detail="OCR service is not ready")
    if not _structure_enabled():
        raise HTTPException(status_code=404, detail="PP-StructureV3 is disabled")

    start = time.perf_counter()
    try:
        image_bytes = base64.b64decode(request.image)
        # prepare_image decodes the pixel data; a truncated/corrupt payload that
        # fails there is still a client error (400), not a server fault.
        _original, ocr_image, _scale_x, _scale_y = prepare_image(image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image") from exc

    # Both Paddle inference passes (structure + char boxes) run in worker
    # threads under the module lock so /health stays responsive while keeping
    # the single-request serial semantics (predictors are not thread-safe).
    async with _infer_lock:
        try:
            items = await asyncio.to_thread(extract_structure, ocr_image, request)
            mapped = map_boxes_to_original(items)
            _attach_chars(mapped, await asyncio.to_thread(_extract_char_boxes, ocr_image))
        finally:
            release_structure_engine_if_configured()
            trim_cuda_cache("structure")

    elapsed = time.perf_counter() - start
    print(f"[OCR] Structure {len(mapped)} boxes in {elapsed:.2f}s", flush=True)
    return OCRResponse(boxes=mapped, model="PP-StructureV3", elapsed=elapsed)


if __name__ == "__main__":
    import uvicorn

    print("[OCR] Initializing PaddleOCR sidecar ...", flush=True)
    init_ocr()
    warmup_structure()
    print("[OCR] Service ready, starting HTTP server ...", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("OCR_PORT", "8082")), workers=1)
