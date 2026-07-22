"""Specialized signature detector service — conditional-detr (Apache-2.0),
trained ONLY on signatures, so it structurally does not fire on printed text /
labels the way the LocateAnything grounding VLM does. Replaces the LA signature
channel. Deterministic (no sampling variance). Hybrid input:

  * full page resized to the model's native 640x640 — recovers signatures that
    are a large-enough, crisp fraction of the page (clean scans: NVIDIA/Banco
    2/2 out of the box).
  * ONLY if the full page finds nothing, tile the page (2/5 windows, half-window
    step) and detect per tile at 640 — a small photographed signature (海油,
    ~10% of a 500px phone photo) then fills enough of the crop to clear the
    model's small-object floor. Gated on the full-page miss, so clean scans pay
    one ~15ms pass and only hard pages tile.
"""
import base64
import io
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", "/data/ubuntu/lh/hf_cache")

import torch
import uvicorn
from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel
from transformers import AutoImageProcessor, AutoModelForObjectDetection

MODEL = os.environ.get("SIGDET_MODEL", "tech4humans/conditional-detr-50-signature-detector")
THR = float(os.environ.get("SIGDET_THRESHOLD", "0.4"))
PORT = int(os.environ.get("SIGDET_PORT", "28150"))
DEV = "cuda" if torch.cuda.is_available() else "cpu"

print(f"[sigdet] loading {MODEL} on {DEV} ...", flush=True)
proc = AutoImageProcessor.from_pretrained(MODEL)
model = AutoModelForObjectDetection.from_pretrained(MODEL).to(DEV).eval()
print("[sigdet] ready", flush=True)

app = FastAPI()


class Req(BaseModel):
    image_base64: str
    threshold: float | None = None


def _slide(total: int, win: int) -> list[int]:
    if total <= win:
        return [0]
    step = max(1, win // 2)
    ps = list(range(0, total - win + 1, step))
    if ps[-1] != total - win:
        ps.append(total - win)
    return ps


def _infer(im: Image.Image, thr: float):
    W, H = im.size
    inp = proc(images=im, return_tensors="pt", size={"height": 640, "width": 640}).to(DEV)
    with torch.no_grad():
        out = model(**inp)
    r = proc.post_process_object_detection(
        out, target_sizes=torch.tensor([[H, W]]).to(DEV), threshold=thr
    )[0]
    return [
        (b[0].item(), b[1].item(), b[2].item(), b[3].item(), s.item())
        for s, b in zip(r["scores"], r["boxes"])
    ]


def _tiled(im: Image.Image, thr: float):
    W, H = im.size
    ww, hh = max(1, W * 2 // 5), max(1, H * 2 // 5)
    found = []
    for y0 in _slide(H, hh):
        for x0 in _slide(W, ww):
            crop = im.crop((x0, y0, x0 + ww, y0 + hh))
            cW, cH = crop.size
            inp = proc(images=crop, return_tensors="pt", size={"height": 640, "width": 640}).to(DEV)
            with torch.no_grad():
                out = model(**inp)
            r = proc.post_process_object_detection(
                out, target_sizes=torch.tensor([[cH, cW]]).to(DEV), threshold=thr
            )[0]
            for s, b in zip(r["scores"], r["boxes"]):
                bx0, by0, bx1, by1 = b.tolist()
                # whole-tile box = detector failed to localise inside the crop -> drop
                if bx0 <= 2 and by0 <= 2 and bx1 >= cW - 2 and by1 >= cH - 2:
                    continue
                found.append((x0 + bx0, y0 + by0, x0 + bx1, y0 + by1, s.item()))
    # dedup by center proximity, keep max score
    found.sort(key=lambda t: -t[4])
    kept = []
    for f in found:
        cx, cy = (f[0] + f[2]) / 2, (f[1] + f[3]) / 2
        if not any(
            abs(cx - (k[0] + k[2]) / 2) < 0.06 * W and abs(cy - (k[1] + k[3]) / 2) < 0.05 * H
            for k in kept
        ):
            kept.append(f)
    return kept


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "threshold": THR}


@app.post("/detect")
def detect(req: Req):
    thr = float(req.threshold if req.threshold is not None else THR)
    data = base64.b64decode(req.image_base64)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    W, H = im.size
    raw = _infer(im, thr)
    mode = "full"
    if not raw:
        raw = _tiled(im, thr)
        mode = "tiled"
    boxes = []
    for x0, y0, x1, y1, sc in raw:
        boxes.append({
            "x": max(0.0, x0 / W), "y": max(0.0, y0 / H),
            "width": max(0.0, (x1 - x0) / W), "height": max(0.0, (y1 - y0) / H),
            "confidence": round(sc, 4),
        })
    return {"boxes": boxes, "mode": mode}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
