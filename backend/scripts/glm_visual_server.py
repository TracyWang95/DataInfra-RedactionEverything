"""GLM visual-grounding adapter — drop-in replacement for locate_anything_server.

Serves the same surface as the LocateAnything server so the backend's
locate_grounding client works unchanged:

  GET  /health                    — ready when the GLM upstream answers
  POST /detect                    — {image_base64, categories?} -> normalized boxes
  GET  /v1/models                 — proxied to the GLM vLLM server
  POST /v1/chat/completions       — proxied (model rewritten, thinking disabled,
                                    <think> blocks stripped from the reply)

Detection is one multi-category prompt per request: unlike LocateAnything,
GLM's recall does not collapse when categories share a prompt (validated on
the 2026-07-06 ablation set), and page-scale objects and margin slivers are
both found on the full frame — no tiling, no per-category fan-out needed.

Env:
  GLM_BASE_URL        upstream OpenAI-compatible base (default http://127.0.0.1:8120/v1)
  GLM_MODEL_NAME      served model name (default glm-fp8)
  GLM_VISUAL_PORT     listen port (default 8130)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("glm_visual_server")

GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "http://127.0.0.1:8120/v1").rstrip("/")
GLM_MODEL_NAME = os.environ.get("GLM_MODEL_NAME", "glm-fp8")
PORT = int(os.environ.get("GLM_VISUAL_PORT", "8130"))
MODEL_NAME = f"GLM-4.6V-Flash({GLM_MODEL_NAME})"

# Platform visual slugs -> prompt vocabulary. Unknown slugs fall through
# verbatim; custom checklist types use /v1/chat/completions instead.
# The four core descriptions are VERBATIM from the 2026-07-06 ablation prompt.
# Do not embellish them: added qualifiers measurably drop recall (a
# "笔迹，不含印刷体人名" aside made the model skip stamped-over pen signatures —
# the same long-prompt-conservatism lesson as the LocateAnything prompts).
CATEGORY_PROMPTS: dict[str, str] = {
    "official_seal": "公章/印章（红色圆章、方章，包括只露出一部分的骑缝章切片、残章）",
    "signature": "手写签名/手写人名",
    "qr_code": "二维码（包括角落的小水印二维码）",
    "barcode": "条形码",
    "face": "人脸（照片中的人体面部）",
    "fingerprint": "指纹/红色捺印",
    "id_card": "身份证或其他证件卡片",
    "medical_wristband": "医疗腕带",
    "handwriting": "手写文字（非签名的手写内容）",
    "watermark": "水印文字",
    "photo": "人像照片/证件照",
    "palmprint": "掌纹",
    "license_plate": "机动车号牌",
    "bank_card": "银行卡/信用卡",
}
ZH_TO_SLUG = {
    "公章": "official_seal", "印章": "official_seal",
    "签名": "signature", "签字": "signature",
    "二维码": "qr_code", "条形码": "barcode", "条码": "barcode",
    "人脸": "face", "指纹": "fingerprint", "身份证": "id_card",
}

app = FastAPI(title="GLM Visual Adapter", version="1.0.0")
_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0), trust_env=False)


class DetectRequest(BaseModel):
    image_base64: str = Field(...)
    conf: float = Field(default=0.25, ge=0.01, le=1.0)
    categories: list[str] | None = None


def _strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.split("</think>")[-1]


def _build_prompt(categories: list[str]) -> str:
    # Keep the ablation-validated phrasing: the object template must use a
    # "..." placeholder. Inlining the type enum into the template makes it
    # read like a concrete single-object example, and the model then
    # sometimes emits ONE bare object instead of the array.
    lines = [
        f"- {slug}：{CATEGORY_PROMPTS.get(slug, slug)}"
        for slug in categories
    ]
    return (
        "你是文档隐私目标检测器。检测图中所有以下目标：\n"
        + "\n".join(lines)
        + "\n输出严格 JSON 数组，每项 {\"type\": \"...\", \"box_2d\": [x1, y1, x2, y2]}，"
        "坐标为 0-1000 归一化整数（相对图像宽高）。没有目标输出 []。只输出 JSON，不要解释。"
    )


def _extract_items(text: str) -> list[Any]:
    """Tolerant extraction: a proper JSON array, or bare/multiple objects.

    The model occasionally emits a single object (or newline-separated
    objects) instead of the requested array; recover those instead of
    dropping the whole detection.
    """
    match = re.search(r"\[\s*\{.*\}\s*\]", text, re.S)
    if match:
        try:
            arr = json.loads(match.group(0))
            if isinstance(arr, list):
                return arr
        except Exception:
            pass
    items: list[Any] = []
    for obj_text in re.findall(r"\{[^{}]*\}", text):
        try:
            items.append(json.loads(obj_text))
        except Exception:
            continue
    return items


def _parse_boxes(text: str, categories: list[str]) -> list[dict[str, Any]]:
    text = _strip_think(text)
    arr = _extract_items(text)
    requested = set(categories)
    out: list[dict[str, Any]] = []
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("type", "")).strip()
        if slug not in requested:
            slug = ZH_TO_SLUG.get(slug, slug)
        if slug not in requested:
            continue
        box = item.get("box_2d") or item.get("box") or []
        if len(box) != 4:
            continue
        try:
            x1, y1, x2, y2 = [max(0.0, min(1.0, float(v) / 1000.0)) for v in box]
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        out.append({
            "category": slug,
            "x": x1,
            "y": y1,
            "width": x2 - x1,
            "height": y2 - y1,
            "confidence": 0.85,
        })
    return out


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        resp = await _client.get(f"{GLM_BASE_URL}/models", timeout=5.0)
        ready = resp.status_code == 200
    except Exception:
        ready = False
    return {"status": "ok" if ready else "loading", "ready": ready, "model": MODEL_NAME}


@app.post("/detect")
async def detect(req: DetectRequest) -> dict[str, Any]:
    started = time.perf_counter()
    categories = [c for c in (req.categories or list(CATEGORY_PROMPTS)) if c]
    if not categories:
        return {"boxes": [], "elapsed": 0.0, "model": MODEL_NAME}
    image_b64 = req.image_base64
    if "," in image_b64 and image_b64.lower().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    body = {
        "model": GLM_MODEL_NAME,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": _build_prompt(categories)},
            ],
        }],
        "temperature": 0.1,
        "max_tokens": 3000,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    resp = await _client.post(f"{GLM_BASE_URL}/chat/completions", json=body)
    resp.raise_for_status()
    payload = resp.json()
    choice = payload["choices"][0]
    content = choice["message"]["content"]
    boxes = _parse_boxes(content, categories)
    elapsed = time.perf_counter() - started
    usage = payload.get("usage") or {}
    logger.info(
        "detect cats=%d img_b64_len=%d -> %d boxes in %.2fs finish=%s prompt_tok=%s out_tok=%s head=%r",
        len(categories), len(image_b64), len(boxes), elapsed,
        choice.get("finish_reason"), usage.get("prompt_tokens"), usage.get("completion_tokens"),
        content[:60],
    )
    return {"boxes": boxes, "elapsed": elapsed, "model": MODEL_NAME}


@app.get("/v1/models")
async def models() -> Any:
    resp = await _client.get(f"{GLM_BASE_URL}/models")
    return resp.json()


@app.post("/v1/chat/completions")
async def chat_completions(body: dict) -> Any:
    body = dict(body)
    body["model"] = GLM_MODEL_NAME
    body.setdefault("chat_template_kwargs", {"enable_thinking": False})
    resp = await _client.post(f"{GLM_BASE_URL}/chat/completions", json=body)
    data = resp.json()
    try:
        for choice in data.get("choices", []):
            msg = choice.get("message") or {}
            if isinstance(msg.get("content"), str):
                msg["content"] = _strip_think(msg["content"])
    except Exception:
        pass
    return data


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
