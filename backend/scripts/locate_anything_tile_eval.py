"""
Tile-based LocateAnything evaluator.

This keeps local detail for small targets while avoiding full-page MoonViT OOM.
It uses the same HF worker path as locate_anything_eval.py, then maps tile boxes
back to original image coordinates and writes original-size overlays.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from locate_anything_eval import (
    IMAGE_EXTS,
    TASK_PROMPTS,
    LocateAnythingWorker,
    _collect_inputs,
    _parse_boxes,
    _task_list,
    _win_to_wsl_path,
)


def _axis_starts(length: int, tile_size: int, overlap: float) -> list[int]:
    if length <= tile_size:
        return [0]
    stride = max(1, round(tile_size * (1.0 - overlap)))
    starts = [0]
    while starts[-1] + tile_size < length:
        starts.append(min(starts[-1] + stride, length - tile_size))
        if len(starts) > 256:
            break
    return sorted(set(starts))


def _tiles(image: Image.Image, tile_size: int, overlap: float) -> list[dict[str, Any]]:
    width, height = image.size
    tiles: list[dict[str, Any]] = []
    for top in _axis_starts(height, tile_size, overlap):
        for left in _axis_starts(width, tile_size, overlap):
            right = min(width, left + tile_size)
            bottom = min(height, top + tile_size)
            crop = image.crop((left, top, right, bottom))
            tiles.append({"left": left, "top": top, "width": right - left, "height": bottom - top, "image": crop})
    return tiles


def _area(box: dict[str, Any]) -> float:
    return max(0.0, float(box["width"])) * max(0.0, float(box["height"]))


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["width"]), ay1 + float(a["height"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["width"]), by1 + float(b["height"])
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    denom = _area(a) + _area(b) - inter
    return inter / denom if denom > 0 else 0.0


def _nms(boxes: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda item: (item.get("score", 1.0), _area(item)), reverse=True):
        if all(_iou(box, other) < threshold for other in kept):
            kept.append(box)
    return kept


def _map_box(box: dict[str, Any], tile: dict[str, Any], task: str) -> dict[str, Any]:
    mapped = dict(box)
    mapped["x"] = round(float(box["x"]) + tile["left"], 2)
    mapped["y"] = round(float(box["y"]) + tile["top"], 2)
    mapped["tile"] = {
        "left": tile["left"],
        "top": tile["top"],
        "width": tile["width"],
        "height": tile["height"],
    }
    mapped["task"] = task
    mapped["score"] = 1.0
    return mapped


def _draw_overlay(image: Image.Image, task_boxes: dict[str, list[dict[str, Any]]], out_path: Path) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    colors = {
        "signature": (22, 163, 74),
        "name": (37, 99, 235),
        "seal": (220, 38, 38),
        "text": (234, 88, 12),
        "layout": (147, 51, 234),
        "signature_point": (20, 184, 166),
    }
    for task, boxes in task_boxes.items():
        color = colors.get(task, (234, 88, 12))
        for idx, box in enumerate(boxes, start=1):
            x, y, w, h = float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
            draw.rectangle((x, y, x + w, y + h), outline=color, width=4)
            label = f"{task}:{idx}"
            draw.rectangle((x, max(0, y - 22), x + 9 * len(label) + 8, y), fill=(255, 255, 255))
            draw.text((x + 4, max(0, y - 20)), label, fill=color)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/mnt/d/has_models/LocateAnything-3B-HF")
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--tasks", default="signature")
    parser.add_argument("--out-dir", default="tmp/locateanything-tile-eval")
    parser.add_argument("--tile-size", type=int, default=1024)
    parser.add_argument("--overlap", type=float, default=0.15)
    parser.add_argument("--nms-threshold", type=float, default=0.35)
    parser.add_argument("--generation-mode", choices=["fast", "slow", "hybrid"], default="hybrid")
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--dtype", choices=["bfloat16", "float16", "float32"], default="bfloat16")
    args = parser.parse_args()

    tasks = _task_list(args.tasks)
    inputs = [path for path in _collect_inputs(args.input, args.recursive) if path.suffix.lower() in IMAGE_EXTS]
    if not inputs:
        print("[fail] no supported image inputs", flush=True)
        return 2

    out_dir = _win_to_wsl_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    worker = LocateAnythingWorker(args.model, backend="hf", dtype_name=args.dtype)

    manifest: list[dict[str, Any]] = []
    for path in inputs:
        image = Image.open(path)
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        width, height = image.size
        tiles = _tiles(image, args.tile_size, args.overlap)
        print(f"[run] {path} size={width}x{height} tiles={len(tiles)}", flush=True)
        task_boxes: dict[str, list[dict[str, Any]]] = {task: [] for task in tasks}
        tile_records: list[dict[str, Any]] = []
        for tile_idx, tile in enumerate(tiles, start=1):
            tile_image = tile["image"]
            tile_record = {"tile_index": tile_idx, "left": tile["left"], "top": tile["top"], "tasks": {}}
            for task in tasks:
                start = time.perf_counter()
                answer = worker.predict(
                    image=tile_image,
                    prompt=TASK_PROMPTS[task],
                    generation_mode=args.generation_mode,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                )
                elapsed = time.perf_counter() - start
                boxes = [_map_box(box, tile, task) for box in _parse_boxes(answer, tile["width"], tile["height"])]
                task_boxes[task].extend(boxes)
                tile_record["tasks"][task] = {
                    "elapsed": round(elapsed, 3),
                    "box_count": len(boxes),
                    "boxes": boxes,
                    "answer": answer,
                }
                print(f"[tile] {path.name} #{tile_idx}/{len(tiles)} {task}: {len(boxes)} boxes in {elapsed:.2f}s", flush=True)
            tile_records.append(tile_record)

        for task in tasks:
            task_boxes[task] = _nms(task_boxes[task], args.nms_threshold)

        page_name = path.stem
        overlay_path = out_dir / f"{page_name}-tile-overlay.png"
        json_path = out_dir / f"{page_name}-tile.json"
        _draw_overlay(image, task_boxes, overlay_path)
        record = {
            "source": str(path),
            "width": width,
            "height": height,
            "tile_size": args.tile_size,
            "overlap": args.overlap,
            "tasks": {task: {"box_count": len(boxes), "boxes": boxes} for task, boxes in task_boxes.items()},
            "tiles": tile_records,
            "json_path": str(json_path),
            "overlay_path": str(overlay_path),
        }
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append(record)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
