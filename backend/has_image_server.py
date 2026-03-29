"""
HaS Image (Ultralytics YOLO11) 独立微服务
端口: 8081（与 PaddleOCR 8082、HaS NER 8080 并列）

API:
  GET  /health
  POST /detect  —  body: image_base64, conf?, categories? (英文 slug 列表，空=全类)
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from io import BytesIO
from typing import Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.has_image_categories import (  # noqa: E402
    SLUG_TO_CLASS_ID,
    class_index_to_slug,
    slug_list_to_class_indices,
)

app = FastAPI(title="HaS Image Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_model = None
_ready = False
_weights_path = ""


def _default_weights() -> str:
    w = os.environ.get("HAS_IMAGE_WEIGHTS", "").strip()
    if w:
        return w
    models_dir = os.environ.get("HAS_MODELS_DIR", "").strip()
    if models_dir:
        optional_pt = os.path.join(models_dir, "sensitive_seg_best.pt")
        if os.path.isfile(optional_pt):
            return optional_pt
    fixed = r"D:\has_models\sensitive_seg_best.pt"
    if os.path.isfile(fixed):
        return fixed
    # 可选：与 README 建议目录树一致——仓库与 has_models 同处「工作区」下
    repo_root = os.path.dirname(ROOT)
    workspace = os.path.dirname(repo_root)
    optional_pt = os.path.join(workspace, "has_models", "sensitive_seg_best.pt")
    if os.path.isfile(optional_pt):
        return optional_pt
    return os.path.join(ROOT, "models", "has_image", "sensitive_seg_best.pt")


def init_model() -> None:
    global _model, _ready, _weights_path
    _weights_path = _default_weights()
    if not os.path.isfile(_weights_path):
        print(f"[HaS-Image] WARN: 权重不存在: {_weights_path}", flush=True)
        print("[HaS-Image] 请从 Hugging Face xuanwulab/HaS_Image_0209_FP32 下载 sensitive_seg_best.pt", flush=True)
        _ready = False
        return
    try:
        from ultralytics import YOLO
    except ImportError as e:
        print(f"[HaS-Image] FATAL: pip install ultralytics — {e}", flush=True)
        sys.exit(1)
    print(f"[HaS-Image] Loading {_weights_path} ...", flush=True)
    _model = YOLO(_weights_path)
    _ready = True
    print("[HaS-Image] Ready.", flush=True)


class DetectRequest(BaseModel):
    image_base64: str = Field(..., description="图片 base64（可含 data URL 前缀）")
    conf: float = Field(default=0.25, ge=0.01, le=1.0)
    categories: Optional[List[str]] = Field(
        default=None,
        description="英文 category slug 列表，空或 null 表示 21 类全跑",
    )


class DetectBox(BaseModel):
    x: float
    y: float
    width: float
    height: float
    category: str
    confidence: float


class DetectResponse(BaseModel):
    boxes: List[DetectBox]
    elapsed: float
    model: str


def _decode_b64(data: str) -> bytes:
    s = data.strip()
    if "," in s and s.lower().startswith("data:"):
        s = s.split(",", 1)[1]
    return base64.b64decode(s, validate=False)


def _predict_sync(image_bytes: bytes, conf: float, classes: Optional[List[int]]) -> List[DetectBox]:
    if _model is None:
        return []
    if classes is not None and len(classes) == 0:
        return []
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    kwargs: dict[str, Any] = {"conf": conf, "verbose": False}
    if classes is not None:
        kwargs["classes"] = classes
    results = _model.predict(img, **kwargs)
    out: List[DetectBox] = []
    if not results:
        return out
    r0 = results[0]
    if r0.boxes is None or len(r0.boxes) == 0:
        return out
    xyxy = r0.boxes.xyxy.cpu().numpy()
    cls = r0.boxes.cls.cpu().numpy()
    cf = r0.boxes.conf.cpu().numpy()
    for i in range(len(xyxy)):
        x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
        xi = max(0.0, x1 / w)
        yi = max(0.0, y1 / h)
        wi = max(0.0, (x2 - x1) / w)
        hi = max(0.0, (y2 - y1) / h)
        cid = int(cls[i])
        slug = class_index_to_slug(cid)
        out.append(
            DetectBox(
                x=xi,
                y=yi,
                width=wi,
                height=hi,
                category=slug,
                confidence=float(cf[i]),
            )
        )
    return out


@app.get("/health")
async def health():
    return {
        "status": "ok" if _ready else "unavailable",
        "ready": _ready,
        "model": "HaS-Image-YOLO11",
        "weights": _weights_path,
    }


@app.post("/detect", response_model=DetectResponse)
async def detect(req: DetectRequest):
    if not _ready:
        raise HTTPException(status_code=503, detail="模型未加载或权重缺失")
    try:
        raw = _decode_b64(req.image_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")
    classes = slug_list_to_class_indices(req.categories)
    # 显式空列表或全部为非法 slug → 不跑推理
    if classes is not None and len(classes) == 0:
        return DetectResponse(boxes=[], elapsed=0.0, model=os.path.basename(_weights_path))
    start = time.perf_counter()
    loop = asyncio.get_event_loop()
    boxes = await loop.run_in_executor(
        None,
        lambda: _predict_sync(raw, req.conf, classes),
    )
    elapsed = time.perf_counter() - start
    print(f"[HaS-Image] {len(boxes)} boxes in {elapsed:.2f}s", flush=True)
    return DetectResponse(boxes=boxes, elapsed=elapsed, model=os.path.basename(_weights_path))


@app.on_event("startup")
async def startup():
    init_model()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("HAS_IMAGE_PORT", "8081"))
    uvicorn.run("has_image_server:app", host="0.0.0.0", port=port, workers=1)
