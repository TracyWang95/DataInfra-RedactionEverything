from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


BOX_RE = re.compile(r"<box><(\d+)><(\d+)><(\d+)><(\d+)></box>")


def _win_to_wsl_path(raw: str) -> Path:
    value = raw.strip().strip('"')
    if re.match(r"^[A-Za-z]:[\\/]", value):
        drive = value[0].lower()
        rest = value[2:].replace("\\", "/").lstrip("/")
        return Path(f"/mnt/{drive}/{rest}")
    return Path(value)


def _prepare_imports(batch_src: str) -> None:
    src = str(_win_to_wsl_path(batch_src))
    if src not in sys.path:
        sys.path.insert(0, src)


class PredictRequest(BaseModel):
    images: list[str] = Field(..., min_length=1)
    prompts: list[str] = Field(..., min_length=1)
    max_new_tokens: int = 512
    temperature: float = 0.0
    repetition_penalty: float = 1.0
    generation_mode: str = "fast"


class ServerState:
    started_at: float
    load_sec: float | None = None
    model_loaded: bool = False


state = ServerState()
state.started_at = time.time()
app = FastAPI(title="LocateAnything Batch Sidecar")


def _load_model() -> None:
    from locateanything_batch import load
    import locateanything_batch.engine as engine

    start = time.perf_counter()
    tok, proc, _model = load()
    if hasattr(proc, "tokenizer"):
        proc.tokenizer = tok
    engine._tok = tok
    engine._proc = proc
    state.load_sec = time.perf_counter() - start
    state.model_loaded = True


def _parse_boxes(answer: str, image_size: tuple[int, int], original_size: tuple[int, int]) -> list[dict[str, Any]]:
    proc_w, proc_h = image_size
    orig_w, orig_h = original_size
    boxes: list[dict[str, Any]] = []
    for match in BOX_RE.finditer(answer):
        x1, y1, x2, y2 = [int(v) for v in match.groups()]
        boxes.append(
            {
                "norm": [x1, y1, x2, y2],
                "processed_xywh": [
                    x1 * proc_w / 1000,
                    y1 * proc_h / 1000,
                    (x2 - x1) * proc_w / 1000,
                    (y2 - y1) * proc_h / 1000,
                ],
                "original_xywh": [
                    x1 * orig_w / 1000,
                    y1 * orig_h / 1000,
                    (x2 - x1) * orig_w / 1000,
                    (y2 - y1) * orig_h / 1000,
                ],
            }
        )
    return boxes


@app.on_event("startup")
def startup() -> None:
    _load_model()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": state.model_loaded,
        "load_sec": state.load_sec,
        "uptime_sec": time.time() - state.started_at,
        "model": os.environ.get("LA3B_MODEL"),
    }


@app.post("/predict")
def predict(req: PredictRequest) -> dict[str, Any]:
    from PIL import Image
    from locateanything_batch import generate_batch_grouped, load_pil

    paths = [_win_to_wsl_path(path) for path in req.images]
    images = [load_pil(path) for path in paths]
    original_sizes = [Image.open(path).size for path in paths]
    groups = [(image, req.prompts) for image in images]

    start = time.perf_counter()
    grouped_answers = generate_batch_grouped(
        groups,
        max_new_tokens=req.max_new_tokens,
        temperature=req.temperature,
        repetition_penalty=req.repetition_penalty,
    )
    infer_sec = time.perf_counter() - start

    results = []
    for path, image, original_size, answers in zip(paths, images, original_sizes, grouped_answers):
        prompt_results = []
        for prompt, answer in zip(req.prompts, answers):
            prompt_results.append(
                {
                    "prompt": prompt,
                    "raw": answer,
                    "boxes": _parse_boxes(answer, image.size, original_size),
                }
            )
        results.append(
            {
                "path": str(path),
                "processed_size": list(image.size),
                "original_size": list(original_size),
                "prompts": prompt_results,
            }
        )

    return {
        "ok": True,
        "infer_sec": infer_sec,
        "images": len(paths),
        "prompts": len(req.prompts),
        "results": results,
    }


@app.post("/predict_flat")
def predict_flat(req: PredictRequest) -> dict[str, Any]:
    from PIL import Image
    from locateanything_batch import generate_batch, load_pil

    paths = [_win_to_wsl_path(path) for path in req.images]
    images = [load_pil(path) for path in paths]
    original_sizes = [Image.open(path).size for path in paths]
    pairs = [(image, prompt) for image in images for prompt in req.prompts]

    start = time.perf_counter()
    flat_answers = generate_batch(
        pairs,
        max_new_tokens=req.max_new_tokens,
        temperature=req.temperature,
        repetition_penalty=req.repetition_penalty,
    )
    infer_sec = time.perf_counter() - start

    results = []
    cursor = 0
    for path, image, original_size in zip(paths, images, original_sizes):
        prompt_results = []
        for prompt in req.prompts:
            answer = flat_answers[cursor]
            cursor += 1
            prompt_results.append(
                {
                    "prompt": prompt,
                    "raw": answer,
                    "boxes": _parse_boxes(answer, image.size, original_size),
                }
            )
        results.append(
            {
                "path": str(path),
                "processed_size": list(image.size),
                "original_size": list(original_size),
                "prompts": prompt_results,
            }
        )

    return {
        "ok": True,
        "infer_sec": infer_sec,
        "images": len(paths),
        "prompts": len(req.prompts),
        "results": results,
    }


@app.post("/predict_stock")
def predict_stock(req: PredictRequest) -> dict[str, Any]:
    from PIL import Image
    import locateanything_batch.engine as engine

    tok, _proc, model = engine.load()
    paths = [_win_to_wsl_path(path) for path in req.images]
    loaded_images = [engine.load_pil(path) for path in paths]
    original_sizes = [Image.open(path).size for path in paths]

    start = time.perf_counter()
    all_results = []
    for path, image, original_size in zip(paths, loaded_images, original_sizes):
        prompt_results = []
        for prompt in req.prompts:
            inp = engine._proc_full(image, prompt)
            output = model.generate(
                pixel_values=inp["pixel_values"].to(engine.DT),
                input_ids=inp["input_ids"],
                attention_mask=inp["attention_mask"],
                image_grid_hws=inp["image_grid_hws"],
                tokenizer=tok,
                max_new_tokens=req.max_new_tokens,
                use_cache=True,
                generation_mode=req.generation_mode,
                temperature=req.temperature,
                do_sample=req.temperature > 0,
                repetition_penalty=req.repetition_penalty,
                verbose=False,
            )
            answer = output[0] if isinstance(output, tuple) else output
            prompt_results.append(
                {
                    "prompt": prompt,
                    "raw": answer,
                    "boxes": _parse_boxes(answer, image.size, original_size),
                }
            )
        all_results.append(
            {
                "path": str(path),
                "processed_size": list(image.size),
                "original_size": list(original_size),
                "prompts": prompt_results,
            }
        )

    return {
        "ok": True,
        "infer_sec": time.perf_counter() - start,
        "images": len(paths),
        "prompts": len(req.prompts),
        "results": all_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--batch-src", default="/mnt/d/tmp/LocateAnything-3B-batch/src")
    parser.add_argument("--model", default="/mnt/d/has_models/LocateAnything-3B-HF")
    args = parser.parse_args()

    _prepare_imports(args.batch_src)
    os.environ.setdefault("LA3B_MODEL", args.model)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("MTP_FLASH_PREFILL", "0")

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
