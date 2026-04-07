"""
PaddleOCR-VL 独立微服务
端口: 8082
与 HaS NER(8080)、HaS Image YOLO(8081) 架构一致，独立进程运行

API:
  GET  /health          - 健康检查
  POST /ocr             - OCR识别（接收图片base64，返回文本块列表）
"""

import os
import threading
import traceback
import base64
import time
import json
import numpy as np
from io import BytesIO
from dataclasses import dataclass, asdict
from typing import List, Optional

from PIL import Image, ImageOps, ImageDraw

# FastAPI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="PaddleOCR-VL Service", version="1.0.0")
# WARNING: 生产环境应限制为具体域名，避免 CSRF 风险
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# OCR 引擎
# ============================================================

_vl = None
_ocr = None
_ready = False
_model_name = "PaddleOCR-VL-1.5"
_paddle_device: str = ""
MAX_SIDE = 1600


def _ocr_fatal(rc: int = 1) -> None:
    """致命错误须退出进程。初始化在后台线程运行时不能用 sys.exit（只结束线程）。"""
    os._exit(rc)


def _ocr_allow_cpu() -> bool:
    """仅当显式设置 OCR_ALLOW_CPU=1 时允许 CPU（不推荐）。"""
    return os.environ.get("OCR_ALLOW_CPU", "").strip().lower() in ("1", "true", "yes")


def _require_gpu_or_exit() -> None:
    """
    默认强制 GPU：未安装 paddlepaddle-gpu、无可用 GPU 时直接退出进程。
    临时允许 CPU：设置环境变量 OCR_ALLOW_CPU=1（仅调试用）。
    """
    global _paddle_device
    if _ocr_allow_cpu():
        print(
            "[OCR] WARN: OCR_ALLOW_CPU=1 — 已允许 CPU 推理，速度会显著变慢；生产环境请勿使用。",
            flush=True,
        )
        try:
            import paddle

            if paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                paddle.set_device("gpu:0")
                _paddle_device = str(paddle.get_device())
                print(f"[OCR] 仍优先使用 {_paddle_device}", flush=True)
        except Exception as e:
            print(f"[OCR] CPU 模式下 device 设置: {e}", flush=True)
        return

    try:
        import paddle
    except ImportError as e:
        print(f"[OCR] FATAL: 未安装 paddle: {e}", flush=True)
        _ocr_fatal(1)

    if not paddle.is_compiled_with_cuda():
        print(
            "[OCR] FATAL: 当前为 Paddle **CPU** 构建。本服务默认要求 GPU。\n"
            "  请卸载 paddlepaddle 并安装 paddlepaddle-gpu（与显卡 CUDA 版本匹配）。\n"
            "  Windows 可参考: scripts\\install_paddle_gpu.ps1\n"
            "  若必须临时用 CPU，请设置环境变量 OCR_ALLOW_CPU=1",
            flush=True,
        )
        _ocr_fatal(1)

    try:
        n = paddle.device.cuda.device_count()
    except Exception as e:
        print(f"[OCR] FATAL: 无法枚举 CUDA 设备: {e}", flush=True)
        _ocr_fatal(1)

    if n < 1:
        print(
            "[OCR] FATAL: 未检测到可用 GPU（CUDA device_count=0）。请检查驱动、CUDA 与显卡。\n"
            "  若必须临时用 CPU，请设置环境变量 OCR_ALLOW_CPU=1",
            flush=True,
        )
        _ocr_fatal(1)

    try:
        paddle.set_device("gpu:0")
        _paddle_device = str(paddle.get_device())
        print(
            f"[OCR] Paddle GPU 已就绪: device={_paddle_device}, cuda_compiled=True, "
            f"visible_gpus={n}（禁止 CPU 推理）",
            flush=True,
        )
    except Exception as e:
        print(f"[OCR] FATAL: 无法将 Paddle 置于 GPU: {e}", flush=True)
        _ocr_fatal(1)


def init_ocr():
    global _vl, _ocr, _ready, _model_name
    _require_gpu_or_exit()

    # 优先 PaddleOCR-VL（与 GPU 强制策略一致，不再自动降级到纯 CPU 的 PaddleOCR 2.x）
    try:
        from paddleocr import PaddleOCRVL

        _vl = PaddleOCRVL()
        _ready = True
        _model_name = "PaddleOCR-VL-1.5"
        print(f"[OCR] {_model_name} loaded on {_paddle_device or 'device'}", flush=True)
        warmup()
        return
    except Exception as e:
        print(f"[OCR] FATAL: PaddleOCR-VL 初始化失败: {e}", flush=True)
        if not _ocr_allow_cpu():
            print(
                "[OCR] 未启用 OCR_ALLOW_CPU=1，拒绝降级到 CPU 版 PaddleOCR。请修复环境或查看上方报错。",
                flush=True,
            )
            _ocr_fatal(1)
        _vl = None

    # 仅当 OCR_ALLOW_CPU=1 且 VL 失败时，降级旧版 PaddleOCR（可能仍走 GPU，取决于 paddle 设置）
    try:
        from paddleocr import PaddleOCR

        _ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        _ready = True
        _model_name = "PaddleOCR-2.x"
        print(f"[OCR] {_model_name} loaded (fallback, OCR_ALLOW_CPU=1)", flush=True)
    except Exception as e:
        print(f"[OCR] All OCR init failed: {e}", flush=True)
        _ready = False


def warmup():
    """预热模型"""
    if not _vl:
        return
    import tempfile
    try:
        print("[OCR] Warming up...", flush=True)
        img = Image.new('RGB', (300, 200), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((50, 80), "Warmup Test", fill='black')
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            temp_path = f.name
            img.save(f, format='PNG')
        _vl.predict(temp_path, max_new_tokens=256)
        os.remove(temp_path)
        print("[OCR] Warmup complete!", flush=True)
    except Exception as e:
        print(f"[OCR] Warmup failed: {e}", flush=True)


# ============================================================
# 数据模型
# ============================================================

class OCRRequest(BaseModel):
    image: str = Field(..., description="Base64编码的图片数据")
    max_new_tokens: int = Field(default=512, description="最大生成token数")


class OCRBox(BaseModel):
    text: str
    x: float       # 归一化坐标 0-1
    y: float
    width: float
    height: float
    confidence: float = 0.9
    label: str = "text"  # text, title, seal, table 等


class OCRResponse(BaseModel):
    boxes: List[OCRBox]
    model: str
    elapsed: float


# ============================================================
# OCR 核心逻辑
# ============================================================

def extract_vl(image: Image.Image, max_new_tokens: int = 512) -> List[OCRBox]:
    """使用 PaddleOCR-VL 提取"""
    if not _vl:
        return []

    width, height = image.size
    
    def _extract_parsing_boxes(outputs) -> list[dict]:
        raw = []
        if not outputs:
            return raw
        for res in outputs:
            parsing_list = None
            if hasattr(res, "parsing_res_list"):
                parsing_list = res.parsing_res_list
            elif hasattr(res, "__getitem__"):
                try:
                    parsing_list = res["parsing_res_list"]
                except Exception:
                    parsing_list = None

            if parsing_list:
                for blk in parsing_list:
                    try:
                        if isinstance(blk, dict):
                            label = blk.get("block_label", "") or blk.get("label", "") or ""
                            content = blk.get("block_content", "") or blk.get("content", "") or ""
                            box = blk.get("block_bbox", None) or blk.get("bbox", None)
                        else:
                            label = getattr(blk, "label", "") or getattr(blk, "block_label", "") or ""
                            content = getattr(blk, "content", "") or getattr(blk, "block_content", "") or ""
                            box = getattr(blk, "bbox", None) or getattr(blk, "block_bbox", None)
                    except Exception:
                        continue
                    if label == "seal":
                        content = "[公章]"
                    if not box or len(box) != 4:
                        continue
                    if not content and label != "seal":
                        continue
                    raw.append({
                        "text": str(content) if content else "[公章]",
                        "box": [float(x) for x in box],
                        "confidence": 0.9,
                        "label": label,
                    })
        return raw

    def _extract_spotting_boxes(outputs) -> list[dict]:
        raw = []
        if not outputs:
            return raw
        for res in outputs:
            spotting_res = None
            if hasattr(res, "__getitem__"):
                try:
                    spotting_res = res["spotting_res"]
                except Exception:
                    spotting_res = None
            if not spotting_res and hasattr(res, "spotting_res"):
                spotting_res = getattr(res, "spotting_res", None)
            if not spotting_res:
                continue

            polys = spotting_res.get("rec_polys", []) or []
            texts = spotting_res.get("rec_texts", []) or []
            for poly, text in zip(polys, texts):
                if not poly:
                    continue
                try:
                    xs = [float(p[0]) for p in poly]
                    ys = [float(p[1]) for p in poly]
                except Exception:
                    continue
                xmin, xmax = min(xs), max(xs)
                ymin, ymax = min(ys), max(ys)
                if xmax <= xmin or ymax <= ymin:
                    continue
                raw.append({
                    "text": str(text or "").strip(),
                    "box": [xmin, ymin, xmax, ymax],
                    "confidence": 0.9,
                    "label": "spotting",
                })
        return raw

    try:
        import tempfile

        # PaddleOCR-VL on Windows is more stable with a file path input
        # than an in-memory ndarray for layout parsing.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name
            image.save(f, format="PNG")
        try:
            raw_boxes = []
            try:
                outputs = _vl.predict(temp_path, max_new_tokens=max_new_tokens)
                raw_boxes = _extract_parsing_boxes(outputs)
                if raw_boxes:
                    print(f"[OCR] doc_parser parsed {len(raw_boxes)} boxes", flush=True)
                else:
                    print("[OCR] doc_parser returned no parsing boxes; trying spotting fallback", flush=True)
            except Exception as e:
                print(f"[OCR] doc_parser failed: {e}", flush=True)

            if not raw_boxes:
                spotting_outputs = _vl.predict(
                    temp_path,
                    use_layout_detection=False,
                    prompt_label="spotting",
                    max_new_tokens=max_new_tokens,
                )
                raw_boxes = _extract_spotting_boxes(spotting_outputs)
                print(f"[OCR] spotting fallback parsed {len(raw_boxes)} boxes", flush=True)
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass
    except Exception as e:
        print(f"[OCR] predict failed: {e}")
        return []

    if not raw_boxes:
        return []

    # 坐标归一化
    max_x = max(b["box"][2] for b in raw_boxes)
    max_y = max(b["box"][3] for b in raw_boxes)
    if max(max_x, max_y) <= 1.5:
        space_w, space_h = 1.0, 1.0
    else:
        space_w, space_h = float(width), float(height)

    items = []
    for rb in raw_boxes:
        box = rb["box"]
        xmin, ymin, xmax, ymax = box
        xmin = xmin / space_w * width
        ymin = ymin / space_h * height
        xmax = xmax / space_w * width
        ymax = ymax / space_h * height
        if xmin > xmax: xmin, xmax = xmax, xmin
        if ymin > ymax: ymin, ymax = ymax, ymin
        xmin = max(0, min(xmin, width))
        xmax = max(0, min(xmax, width))
        ymin = max(0, min(ymin, height))
        ymax = max(0, min(ymax, height))
        w = max(1.0, xmax - xmin)
        h = max(1.0, ymax - ymin)
        items.append(OCRBox(
            text=rb["text"],
            x=xmin / width,
            y=ymin / height,
            width=w / width,
            height=h / height,
            confidence=rb["confidence"],
            label=rb.get("label", "text"),
        ))
    return items


def prepare_image(image_bytes: bytes) -> tuple:
    """准备OCR输入图片"""
    original = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes)).convert("RGB"))
    orig_w, orig_h = original.size
    max_side = max(orig_w, orig_h)
    if max_side > MAX_SIDE:
        scale = MAX_SIDE / max_side
        ocr_w, ocr_h = int(orig_w * scale), int(orig_h * scale)
        ocr_image = original.resize((ocr_w, ocr_h), Image.Resampling.LANCZOS)
    else:
        ocr_image = original
        ocr_w, ocr_h = orig_w, orig_h
    scale_x = ocr_w / orig_w if orig_w else 1.0
    scale_y = ocr_h / orig_h if orig_h else 1.0
    return original, ocr_image, scale_x, scale_y


# ============================================================
# API 端点
# ============================================================

@app.get("/health")
async def health():
    gpu_ok = False
    dev = _paddle_device
    try:
        import paddle

        gpu_ok = bool(paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0)
        if not dev:
            dev = str(paddle.get_device())
    except Exception:
        pass
    return {
        "status": "online" if _ready else "offline",
        "model": _model_name,
        "ready": _ready,
        "gpu_available": gpu_ok,
        "device": dev or "unknown",
        "gpu_only_mode": not _ocr_allow_cpu(),
    }


@app.post("/ocr", response_model=OCRResponse)
async def ocr_extract(request: OCRRequest):
    if not _ready:
        raise HTTPException(status_code=503, detail="OCR service not ready")

    start = time.perf_counter()

    # 解码图片
    try:
        image_bytes = base64.b64decode(request.image)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")

    original, ocr_image, scale_x, scale_y = prepare_image(image_bytes)

    # PaddleOCR-VL is not stable when invoked from a worker thread
    # in this Windows setup, so keep inference on the main thread.
    items = extract_vl(ocr_image, max_new_tokens=request.max_new_tokens)

    # 坐标映射回原图
    mapped = []
    for item in items:
        mapped.append(OCRBox(
            text=item.text,
            x=item.x * scale_x,
            y=item.y * scale_y,
            width=item.width * scale_x,
            height=item.height * scale_y,
            confidence=item.confidence,
            label=item.label,
        ))

    elapsed = time.perf_counter() - start
    print(f"[OCR] {len(mapped)} boxes in {elapsed:.2f}s")

    return OCRResponse(boxes=mapped, model=_model_name, elapsed=elapsed)


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print("[OCR] Initializing model in main thread ...", flush=True)
    init_ocr()
    print("[OCR] Model ready, starting HTTP server ...", flush=True)
    port = int(os.environ.get("OCR_PORT", "8082"))
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
