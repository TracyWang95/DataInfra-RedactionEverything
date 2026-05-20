"""
MinerU（ModelScope / OpenDataLab）OCR 独立微服务
端口: 8082
与 HaS NER(8080)、HaS Image YOLO(8081) 架构一致，独立进程运行

API:
  GET  /health          - 健康检查
  POST /ocr             - OCR识别（接收图片 base64，返回文本块列表）

本地模型（推荐离线环境）:
  先执行: python scripts/download_mineru_models_modelscope.py
  默认目录为 <backend>/models/mineru。若该目录下存在 models/ 子目录，本服务会自动设置
  MINERU_MODEL_SOURCE=local，并在同目录写入 / 更新 mineru.json（models-dir.pipeline）。
  也可设置环境变量 OCR_MINERU_MODELS_DIR 指向其它已下载根目录。
"""

import json
import os
from pathlib import Path


def _backend_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _configure_local_mineru_models() -> None:
    """
    MinerU 在 MINERU_MODEL_SOURCE=local 时从 mineru.json 的 models-dir.pipeline 读取根目录，
    该根目录下须有 models/（与 ModelScope 快照 layout 一致）。
    检测到就绪的本地目录后，写入 mineru.json 并指向该文件，避免依赖用户家目录配置。
    """
    override = os.environ.get("OCR_MINERU_MODELS_DIR", "").strip()
    root = Path(override).resolve() if override else (_backend_dir() / "models" / "mineru").resolve()
    if not (root / "models").is_dir():
        return

    cfg_path = root / "mineru.json"
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = {}
    cfg.setdefault("config_version", "1.3.1")
    md = cfg.get("models-dir")
    if not isinstance(md, dict):
        md = {}
    md["pipeline"] = str(root)
    cfg["models-dir"] = md
    try:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[OCR] WARN: 无法写入 {cfg_path}: {e}", flush=True)
        return

    os.environ["MINERU_TOOLS_CONFIG_JSON"] = str(cfg_path)
    os.environ["MINERU_MODEL_SOURCE"] = "local"
    print(f"[OCR] 使用本地 MinerU pipeline 模型目录: {root}", flush=True)


def _configure_remote_model_env() -> None:
    """
    在首次导入 MinerU（内部会拉 huggingface_hub / ModelScope）之前设置：
    - 国内常用 HF 镜像，减轻访问 huggingface.co 超时；
    - 延长 huggingface_hub 默认 10s 超时，避免弱网下 ConnectTimeout。

    均可通过环境变量在启动前覆盖。
    """
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "120")
    os.environ.setdefault("MODELSCOPE_DOMAIN", "www.modelscope.cn")


_configure_remote_model_env()
_configure_local_mineru_models()

# MinerU 3.x：PPDocLayoutV2Config 在 super().__init__ 之后才设置 reading_order_config；
# 新版 transformers 会在父类初始化期间校验并调用 to_dict()，触发 AttributeError。
_pp_doclayout_patch_applied = False


def _patch_mineru_pp_doclayout_config_for_transformers() -> None:
    global _pp_doclayout_patch_applied
    if _pp_doclayout_patch_applied:
        return
    if os.environ.get("OCR_SKIP_MINERU_PPDOC_LAYOUT_PATCH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    try:
        import mineru.model.layout.pp_doclayoutv2 as m
        from transformers.models.rt_detr.modeling_rt_detr import RTDetrForObjectDetection
    except ImportError:
        return

    def _fixed_init(
        self,
        backbone_config=None,
        class_thresholds=None,
        class_order=None,
        reading_order_config=None,
        **kwargs,
    ):
        if backbone_config is None:
            backbone_config = m._build_default_backbone_config()
        if isinstance(reading_order_config, m.PPDocLayoutV2ReadingOrderConfig):
            reading_order = reading_order_config
        else:
            reading_order = m.PPDocLayoutV2ReadingOrderConfig(**(reading_order_config or {}))
        self.reading_order_config = reading_order
        kwargs.pop("reading_order_config", None)
        super(m.PPDocLayoutV2Config, self).__init__(
            backbone_config=backbone_config,
            class_thresholds=class_thresholds or list(m.DEFAULT_CLASS_THRESHOLDS),
            class_order=class_order or list(m.DEFAULT_CLASS_ORDER),
            **kwargs,
        )
        self.class_thresholds = list(class_thresholds or m.DEFAULT_CLASS_THRESHOLDS)
        self.class_order = list(class_order or m.DEFAULT_CLASS_ORDER)
        self.reading_order_config = reading_order

    m.PPDocLayoutV2Config.__init__ = _fixed_init

    def _fixed_od_init(self, config: m.PPDocLayoutV2Config) -> None:
        # 新版 RTDetrForObjectDetection 将 class_embed / bbox_embed 挂在 self.model.decoder 上，
        # 不再作为 self 的属性；MinerU 仍写成 self.model.decoder.class_embed = self.class_embed。
        RTDetrForObjectDetection.__init__(self, config)
        dec = self.model.decoder
        class_embed = getattr(self, "class_embed", None) or dec.class_embed
        bbox_embed = getattr(self, "bbox_embed", None) or dec.bbox_embed
        self.model = m.PPDocLayoutV2Model(config)
        self.model.decoder.class_embed = class_embed
        self.model.decoder.bbox_embed = bbox_embed
        self.reading_order = m.PPDocLayoutV2ReadingOrder(config.reading_order_config)
        self.num_queries = config.num_queries
        self.config = config
        self.post_init()

    m.PPDocLayoutV2ForObjectDetection.__init__ = _fixed_od_init
    _pp_doclayout_patch_applied = True
    print(
        "[OCR] 已启用 PP-DocLayout（Config + ForObjectDetection）与当前 transformers 的兼容性补丁。",
        flush=True,
    )


_patch_mineru_pp_doclayout_config_for_transformers()

import threading
import traceback
import base64
import time
from io import BytesIO
from typing import Any, List

from PIL import Image, ImageOps, ImageDraw

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="MinerU OCR Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

_ready = False
_model_name = "MinerU-pipeline"
_torch_device: str = ""
_infer_lock = threading.Lock()
MAX_SIDE = 1600


def _ocr_fatal(rc: int = 1) -> None:
    os._exit(rc)


def _ocr_allow_cpu() -> bool:
    return os.environ.get("OCR_ALLOW_CPU", "").strip().lower() in ("1", "true", "yes")


def _require_gpu_or_exit() -> None:
    """
    默认要求 CUDA：无 GPU 时退出（与旧 Paddle 微服务策略一致）。
    调试可设 OCR_ALLOW_CPU=1 允许 CPU（MinerU pipeline 支持 CPU，但很慢）。
    """
    global _torch_device
    if _ocr_allow_cpu():
        print(
            "[OCR] WARN: OCR_ALLOW_CPU=1 — 已允许 CPU 推理，速度会显著变慢；生产环境请勿使用。",
            flush=True,
        )
        try:
            import torch

            if torch.cuda.is_available():
                _torch_device = "cuda:0"
                print(f"[OCR] 仍优先使用 {_torch_device}", flush=True)
            else:
                _torch_device = "cpu"
        except Exception as e:
            print(f"[OCR] CPU 模式下 device 探测: {e}", flush=True)
            _torch_device = "cpu"
        return

    try:
        import torch
    except ImportError as e:
        print(f"[OCR] FATAL: 未安装 torch: {e}", flush=True)
        _ocr_fatal(1)

    if not torch.cuda.is_available():
        print(
            "[OCR] FATAL: 未检测到可用 CUDA（torch.cuda.is_available()=False）。\n"
            "  请安装带 CUDA 的 PyTorch，或临时设置 OCR_ALLOW_CPU=1 使用 CPU。\n",
            flush=True,
        )
        _ocr_fatal(1)

    _torch_device = "cuda:0"
    try:
        torch.cuda.set_device(0)
    except Exception as e:
        print(f"[OCR] FATAL: 无法使用 GPU:0 — {e}", flush=True)
        _ocr_fatal(1)

    print(
        f"[OCR] PyTorch GPU 已就绪: device={_torch_device}, "
        f"torch={torch.__version__}（禁止 CPU 推理）",
        flush=True,
    )


def init_ocr():
    global _ready, _model_name
    _require_gpu_or_exit()

    # MinerU 读取 MINERU_DEVICE_MODE / get_device()；显式同步，避免初始化顺序问题
    if not _ocr_allow_cpu():
        os.environ.setdefault("MINERU_DEVICE_MODE", "cuda")
    else:
        os.environ.setdefault("MINERU_DEVICE_MODE", "cpu")

    # OCR 微服务以文字块为主，默认关闭公式以加快首包与推理
    os.environ.setdefault("MINERU_FORMULA_ENABLE", "false")
    os.environ.setdefault("MINERU_TABLE_ENABLE", "true")

    try:
        from mineru.backend.pipeline.pipeline_analyze import batch_image_analyze  # noqa: F401

        custom = os.environ.get("OCR_MODEL_NAME", "").strip()
        _model_name = custom or "MinerU-pipeline (ModelScope)"
        _ready = True
        print(f"[OCR] {_model_name} 依赖已加载，device≈{_torch_device or 'auto'}", flush=True)
        warmup()
    except Exception as e:
        print(f"[OCR] FATAL: MinerU 初始化失败: {e}", flush=True)
        traceback.print_exc()
        _ready = False
        if not _ocr_allow_cpu():
            _ocr_fatal(1)


def warmup():
    try:
        print("[OCR] Warming up ...", flush=True)
        img = Image.new("RGB", (320, 240), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((40, 100), "Warmup", fill="black")
        _ = extract_mineru(img)
        print("[OCR] Warmup complete.", flush=True)
    except Exception as e:
        print(f"[OCR] Warmup failed: {e}", flush=True)
        if "Timeout" in type(e).__name__ or "timed out" in str(e).lower():
            print(
                "[OCR] 提示：首次运行需下载模型；请检查网络/代理，或设置 HF_ENDPOINT、"
                "HF_HUB_DOWNLOAD_TIMEOUT，或预先缓存 ModelScope/HF 权重。",
                flush=True,
            )


class OCRRequest(BaseModel):
    image: str = Field(..., description="Base64编码的图片数据")
    max_new_tokens: int = Field(default=512, description="兼容旧客户端；MinerU 不使用该字段")


class OCRBox(BaseModel):
    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = 0.9
    label: str = "text"


class OCRResponse(BaseModel):
    boxes: List[OCRBox]
    model: str
    elapsed: float


def map_boxes_to_original(items: List[OCRBox]) -> List[OCRBox]:
    mapped: List[OCRBox] = []
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
            )
        )
    return mapped


def _layout_item_to_text_and_label(item: dict[str, Any]) -> tuple[str, str]:
    label = (item.get("label") or "text") or "text"
    raw = item.get("text", "")
    if isinstance(raw, list):
        text = " ".join(str(x) for x in raw if x).strip()
    else:
        text = str(raw).strip() if raw is not None else ""

    if not text and item.get("latex"):
        text = str(item.get("latex", "")).strip()

    if label == "seal":
        if not text:
            text = "[公章]"
    return text, label


def extract_mineru(image: Image.Image) -> List[OCRBox]:
    from mineru.backend.pipeline.pipeline_analyze import batch_image_analyze

    lang = os.environ.get("OCR_LANG", "ch").strip() or "ch"
    formula = os.environ.get("MINERU_FORMULA_ENABLE", "false").lower() in ("1", "true", "yes")
    table = os.environ.get("MINERU_TABLE_ENABLE", "true").lower() not in ("0", "false", "no")

    width, height = image.size
    if width < 1 or height < 1:
        return []

    with _infer_lock:
        layouts = batch_image_analyze(
            [(image, True, lang)],
            formula_enable=formula,
            table_enable=table,
        )

    if not layouts:
        return []

    layout_res: list[dict[str, Any]] = layouts[0]
    raw_boxes: list[dict[str, Any]] = []

    for it in layout_res:
        bbox = it.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        try:
            x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError):
            continue

        text, label = _layout_item_to_text_and_label(it)
        if not text.strip():
            continue

        score = it.get("score", 0.9)
        try:
            conf = float(score) if score is not None else 0.9
        except (TypeError, ValueError):
            conf = 0.9

        raw_boxes.append(
            {
                "text": text,
                "box": [x0, y0, x1, y1],
                "confidence": max(0.0, min(conf, 1.0)),
                "label": label,
            }
        )

    if not raw_boxes:
        return []

    max_x = max(b["box"][2] for b in raw_boxes)
    max_y = max(b["box"][3] for b in raw_boxes)
    if max(max_x, max_y) <= 1.5:
        space_w, space_h = 1.0, 1.0
    else:
        space_w, space_h = float(width), float(height)

    items: List[OCRBox] = []
    for rb in raw_boxes:
        xmin, ymin, xmax, ymax = rb["box"]
        xmin = xmin / space_w * width
        ymin = ymin / space_h * height
        xmax = xmax / space_w * width
        ymax = ymax / space_h * height
        if xmin > xmax:
            xmin, xmax = xmax, xmin
        if ymin > ymax:
            ymin, ymax = ymax, ymin
        xmin = max(0, min(xmin, width))
        xmax = max(0, min(xmax, width))
        ymin = max(0, min(ymin, height))
        ymax = max(0, min(ymax, height))
        w = max(1.0, xmax - xmin)
        h = max(1.0, ymax - ymin)
        items.append(
            OCRBox(
                text=rb["text"],
                x=xmin / width,
                y=ymin / height,
                width=w / width,
                height=h / height,
                confidence=rb["confidence"],
                label=str(rb.get("label", "text")),
            )
        )
    return items


def prepare_image(image_bytes: bytes) -> tuple:
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


@app.get("/health")
async def health():
    gpu_ok = False
    dev = _torch_device
    try:
        import torch

        gpu_ok = bool(torch.cuda.is_available())
        if gpu_ok and not dev:
            dev = str(torch.cuda.current_device())
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

    try:
        image_bytes = base64.b64decode(request.image)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")

    _orig, ocr_image, _scale_x, _scale_y = prepare_image(image_bytes)

    items = extract_mineru(ocr_image)
    mapped = map_boxes_to_original(items)

    elapsed = time.perf_counter() - start
    print(f"[OCR] {len(mapped)} boxes in {elapsed:.2f}s", flush=True)

    return OCRResponse(boxes=mapped, model=_model_name, elapsed=elapsed)


if __name__ == "__main__":
    import uvicorn

    print("[OCR] Initializing MinerU in main thread ...", flush=True)
    init_ocr()
    print("[OCR] Model ready, starting HTTP server ...", flush=True)
    port = int(os.environ.get("OCR_PORT", "8082"))
    uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
