"""
Sidecar evaluator for NVIDIA LocateAnything-3B.

This script is intentionally outside the main runtime path. It loads the model
once, runs grounding prompts on test files, and writes JSON + overlay images.

Recommended use:
  1. Stop the normal local services first to free VRAM.
  2. Run this from WSL with the vLLM/PyTorch environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps


DEFAULT_MODEL_ID = "nv-community/LocateAnything-3B"
DEFAULT_TASKS = ("signature", "name", "seal", "text")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTS = {".pdf"}

TASK_PROMPTS = {
    "signature": (
        "Locate all the instances that match the following description: handwritten signatures "
        "or handwritten signer names in this document image. Do not locate printed labels, dates, "
        "seals, table lines, or plain printed text."
    ),
    "name": (
        "Please locate the text referred as the person name value next to the Chinese label "
        "'\\u59d3\\u540d' or the English label 'name'. Return only the value region, not the label."
    ),
    "seal": "Locate all red stamps or seals in this document image.",
    "text": "Detect all the text in box format.",
    "layout": (
        "Locate all the instances that match the following description: document title, form fields, "
        "tables, text blocks, signature blocks, stamps, and handwritten notes."
    ),
    "signature_point": "Point to: handwritten signature or signer name.",
}


@dataclass(frozen=True)
class PageImage:
    source: Path
    page_index: int
    image: Image.Image
    original_size: tuple[int, int]


def _win_to_wsl_path(raw: str) -> Path:
    value = raw.strip().strip('"')
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
    if match and os.name != "nt":
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    return Path(value)


def _collect_inputs(inputs: list[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = _win_to_wsl_path(raw)
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            files.extend(
                p
                for p in iterator
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS | PDF_EXTS
            )
        elif path.is_file() and path.suffix.lower() in IMAGE_EXTS | PDF_EXTS:
            files.append(path)
        else:
            print(f"[skip] not found or unsupported: {path}", flush=True)
    return sorted(dict.fromkeys(files), key=lambda p: str(p).lower())


def _resize_for_inference(image: Image.Image, max_image_side: int) -> Image.Image:
    if max_image_side <= 0:
        return image
    width, height = image.size
    longest = max(width, height)
    if longest <= max_image_side:
        return image
    scale = max_image_side / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _load_pages(path: Path, max_pdf_pages: int, max_image_side: int = 0) -> list[PageImage]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        image = Image.open(path)
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        original_size = image.size
        image = _resize_for_inference(image, max_image_side)
        return [PageImage(source=path, page_index=0, image=image, original_size=original_size)]

    if suffix in PDF_EXTS:
        try:
            import fitz  # PyMuPDF
        except Exception as exc:  # pragma: no cover - environment dependent
            print(f"[skip] PDF needs PyMuPDF in this env: {path} ({exc})", flush=True)
            return []
        pages: list[PageImage] = []
        doc = fitz.open(str(path))
        try:
            for idx in range(min(len(doc), max(1, max_pdf_pages))):
                page = doc.load_page(idx)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                original_size = image.size
                image = _resize_for_inference(image, max_image_side)
                pages.append(PageImage(source=path, page_index=idx, image=image, original_size=original_size))
        finally:
            doc.close()
        return pages

    return []


def _parse_boxes(answer: str, width: int, height: int) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    ref_pattern = re.compile(r"<ref>(?P<label>.*?)</ref>\s*<box><(?P<x1>\d+)><(?P<y1>\d+)><(?P<x2>\d+)><(?P<y2>\d+)></box>")
    consumed: set[tuple[int, int]] = set()
    for match in ref_pattern.finditer(answer):
        consumed.add(match.span())
        boxes.append(_box_from_match(match, width, height, match.group("label")))

    box_pattern = re.compile(r"<box><(?P<x1>\d+)><(?P<y1>\d+)><(?P<x2>\d+)><(?P<y2>\d+)></box>")
    for match in box_pattern.finditer(answer):
        if any(start <= match.start() and match.end() <= end for start, end in consumed):
            continue
        boxes.append(_box_from_match(match, width, height, ""))
    return boxes


def _parse_points(answer: str, width: int, height: int) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    point_pattern = re.compile(r"<box><(?P<x>\d+)><(?P<y>\d+)></box>")
    for match in point_pattern.finditer(answer):
        x = int(match.group("x"))
        y = int(match.group("y"))
        points.append(
            {
                "x": round(max(0.0, min(width, x / 1000 * width)), 2),
                "y": round(max(0.0, min(height, y / 1000 * height)), 2),
                "normalized": [x, y],
            }
        )
    return points


def _box_from_match(match: re.Match[str], width: int, height: int, label: str) -> dict[str, Any]:
    x1, y1, x2, y2 = (int(match.group(k)) for k in ("x1", "y1", "x2", "y2"))
    left = max(0.0, min(width, x1 / 1000 * width))
    top = max(0.0, min(height, y1 / 1000 * height))
    right = max(0.0, min(width, x2 / 1000 * width))
    bottom = max(0.0, min(height, y2 / 1000 * height))
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return {
        "label": label.strip(),
        "x": round(left, 2),
        "y": round(top, 2),
        "width": round(max(0.0, right - left), 2),
        "height": round(max(0.0, bottom - top), 2),
        "normalized": [x1, y1, x2, y2],
    }


def _draw_overlay(image: Image.Image, task_results: dict[str, Any], out_path: Path) -> None:
    colors = {
        "signature": (22, 163, 74),
        "name": (37, 99, 235),
        "seal": (220, 38, 38),
        "text": (124, 58, 237),
        "layout": (234, 88, 12),
        "signature_point": (14, 165, 233),
    }
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for task, result in task_results.items():
        color = colors.get(task, (234, 88, 12))
        for idx, box in enumerate(result.get("boxes") or [], start=1):
            x = float(box["x"])
            y = float(box["y"])
            w = float(box["width"])
            h = float(box["height"])
            if w <= 0 or h <= 0:
                continue
            draw.rectangle((x, y, x + w, y + h), outline=color, width=3)
            label = f"{task}:{idx}"
            draw.rectangle((x, max(0, y - 18), x + 8 * len(label) + 6, y), fill=(255, 255, 255))
            draw.text((x + 3, max(0, y - 16)), label, fill=color)
        for idx, point in enumerate(result.get("points") or [], start=1):
            x = float(point["x"])
            y = float(point["y"])
            radius = 8
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=4)
            draw.text((x + radius + 2, y - radius), f"{task}:{idx}", fill=color)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


class LocateAnythingWorker:
    def __init__(self, model_path: str, backend: str = "auto", dtype_name: str = "bfloat16") -> None:
        import torch
        from transformers import AutoModel, AutoProcessor, AutoTokenizer

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = getattr(torch, dtype_name)
        resolved = self._resolve_model(model_path, backend)
        print(f"[model] loading {resolved} on {self.device} dtype={dtype_name}", flush=True)
        self.tokenizer = AutoTokenizer.from_pretrained(resolved, trust_remote_code=True)
        self.processor = AutoProcessor.from_pretrained(resolved, trust_remote_code=True)
        self._install_transformers5_compat(resolved)
        self.model = AutoModel.from_pretrained(
            resolved,
            torch_dtype=self.dtype,
            trust_remote_code=True,
        ).to(self.device).eval()

    @staticmethod
    def _resolve_model(model_path: str, backend: str) -> str:
        path = _win_to_wsl_path(model_path)
        if path.exists():
            return str(path)
        if backend in {"auto", "modelscope"} and "/" in model_path and not model_path.startswith("nvidia/"):
            try:
                from modelscope import snapshot_download
            except Exception as exc:
                if backend == "modelscope":
                    raise RuntimeError("modelscope is required for ModelScope model ids") from exc
            else:
                return snapshot_download(model_path)
        return model_path

    @staticmethod
    def _install_transformers5_compat(resolved_model: str) -> None:
        """Adapt LocateAnything remote code to newer Transformers method signatures."""
        try:
            import inspect

            from transformers.dynamic_module_utils import get_class_from_dynamic_module
            from transformers.modeling_utils import PreTrainedModel
        except Exception as exc:
            print(f"[compat] skipped Transformers compatibility check: {exc}", flush=True)
            return

        base_signature = inspect.signature(PreTrainedModel._check_and_adjust_attn_implementation)
        if "allow_all_kernels" not in base_signature.parameters:
            return

        patched: list[str] = []

        def patch_loaded_class(model_cls: type, base_name: str) -> None:
            target_base = next((cls for cls in model_cls.__mro__ if cls.__name__ == base_name), None)
            if target_base is None:
                return

            current = target_base._check_and_adjust_attn_implementation
            current_signature = inspect.signature(current)
            if "allow_all_kernels" in current_signature.parameters:
                return

            def _check_and_adjust_attn_implementation(
                self: Any,
                attn_implementation: str | None,
                is_init_check: bool = False,
                allow_all_kernels: bool = False,
            ) -> str:
                if attn_implementation == "magi":
                    return "magi"
                return PreTrainedModel._check_and_adjust_attn_implementation(
                    self,
                    attn_implementation,
                    is_init_check=is_init_check,
                    allow_all_kernels=allow_all_kernels,
                )

            target_base._check_and_adjust_attn_implementation = _check_and_adjust_attn_implementation
            patched.append(base_name)

        try:
            locate_cls = get_class_from_dynamic_module(
                "modeling_locateanything.LocateAnythingForConditionalGeneration",
                resolved_model,
                local_files_only=Path(resolved_model).exists(),
            )
        except Exception as exc:
            print(f"[compat] could not preload LocateAnything class: {exc}", flush=True)
            return

        patch_loaded_class(locate_cls, "LocateAnythingPreTrainedModel")

        qwen2_cls = getattr(locate_cls.__init__, "__globals__", {}).get("Qwen2ForCausalLM")
        if isinstance(qwen2_cls, type):
            patch_loaded_class(qwen2_cls, "Qwen2PreTrainedModel")
        else:
            try:
                direct_qwen2_cls = get_class_from_dynamic_module(
                    "modeling_qwen2.Qwen2ForCausalLM",
                    resolved_model,
                    local_files_only=Path(resolved_model).exists(),
                )
            except Exception as exc:
                print(f"[compat] could not preload Qwen2 class: {exc}", flush=True)
            else:
                patch_loaded_class(direct_qwen2_cls, "Qwen2PreTrainedModel")

        if patched:
            print(f"[compat] installed Transformers 5.x attention-signature adapter: {', '.join(patched)}", flush=True)

    def predict(
        self,
        image: Image.Image,
        prompt: str,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = self.processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = self.processor.process_vision_info(messages)
        inputs = self.processor(text=[text], images=images, videos=videos, return_tensors="pt").to(self.device)
        pixel_values = inputs["pixel_values"].to(self.dtype)
        response = self.model.generate(
            pixel_values=pixel_values,
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            image_grid_hws=inputs.get("image_grid_hws", None),
            tokenizer=self.tokenizer,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            generation_mode=generation_mode,
            temperature=temperature,
            do_sample=True,
            top_p=0.9,
            repetition_penalty=1.1,
            verbose=False,
        )
        if isinstance(response, tuple):
            response = response[0]
        if isinstance(response, str):
            return response
        if isinstance(response, list) and response and isinstance(response[0], str):
            return response[0]
        if hasattr(response, "shape"):
            return self.tokenizer.decode(response[0], skip_special_tokens=False)
        return str(response)

    def detect(
        self,
        image: Image.Image,
        categories: list[str],
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        cats = "</c>".join(categories)
        prompt = f"Locate all the instances that match the following description: {cats}."
        return self.predict(image, prompt, generation_mode, max_new_tokens, temperature)

    def ground_single(
        self,
        image: Image.Image,
        phrase: str,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        prompt = f"Locate a single instance that matches the following description: {phrase}."
        return self.predict(image, prompt, generation_mode, max_new_tokens, temperature)

    def ground_multi(
        self,
        image: Image.Image,
        phrase: str,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        prompt = f"Locate all the instances that match the following description: {phrase}."
        return self.predict(image, prompt, generation_mode, max_new_tokens, temperature)

    def ground_text(
        self,
        image: Image.Image,
        phrase: str,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        prompt = f"Please locate the text referred as {phrase}."
        return self.predict(image, prompt, generation_mode, max_new_tokens, temperature)

    def detect_text(
        self,
        image: Image.Image,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        return self.predict(image, "Detect all the text in box format.", generation_mode, max_new_tokens, temperature)

    def point(
        self,
        image: Image.Image,
        phrase: str,
        generation_mode: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        return self.predict(image, f"Point to: {phrase}.", generation_mode, max_new_tokens, temperature)


def _task_list(raw: str) -> list[str]:
    tasks = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [task for task in tasks if task not in TASK_PROMPTS]
    if unknown:
        raise SystemExit(f"unknown tasks: {', '.join(unknown)}; allowed: {', '.join(TASK_PROMPTS)}")
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--backend", choices=["auto", "modelscope", "hf"], default="auto")
    parser.add_argument("--input", action="append", required=True, help="File or directory. Windows paths are accepted in WSL.")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--tasks", default=",".join(DEFAULT_TASKS))
    parser.add_argument("--out-dir", default="tmp/locateanything-eval")
    parser.add_argument("--max-pdf-pages", type=int, default=2)
    parser.add_argument("--max-image-side", type=int, default=0, help="Resize the longest side before inference; 0 keeps original size.")
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    parser.add_argument("--generation-mode", choices=["fast", "slow", "hybrid"], default="hybrid")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--dtype", choices=["bfloat16", "float16", "float32"], default="bfloat16")
    args = parser.parse_args()

    tasks = _task_list(args.tasks)
    inputs = _collect_inputs(args.input, args.recursive)
    if not inputs:
        print("[fail] no supported input files", flush=True)
        return 2

    out_dir = _win_to_wsl_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    worker = LocateAnythingWorker(args.model, backend=args.backend, dtype_name=args.dtype)

    manifest: list[dict[str, Any]] = []
    for path in inputs:
        for page in _load_pages(path, args.max_pdf_pages, args.max_image_side):
            image = page.image
            width, height = image.size
            page_name = f"{path.stem}" if page.page_index == 0 else f"{path.stem}-p{page.page_index + 1}"
            print(f"[run] {path} page={page.page_index + 1} size={width}x{height}", flush=True)
            task_results: dict[str, Any] = {}
            for task in tasks:
                start = time.perf_counter()
                answer = worker.predict(
                    image=image,
                    prompt=TASK_PROMPTS[task],
                    generation_mode=args.generation_mode,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                )
                elapsed = time.perf_counter() - start
                boxes = _parse_boxes(answer, width, height)
                points = _parse_points(answer, width, height)
                task_results[task] = {
                    "prompt": TASK_PROMPTS[task],
                    "elapsed": round(elapsed, 3),
                    "box_count": len(boxes),
                    "point_count": len(points),
                    "boxes": boxes,
                    "points": points,
                    "answer": answer,
                }
                print(
                    f"[done] {page_name} {task}: {len(boxes)} boxes, {len(points)} points in {elapsed:.2f}s",
                    flush=True,
                )

            record = {
                "source": str(path),
                "page_index": page.page_index,
                "width": width,
                "height": height,
                "original_width": page.original_size[0],
                "original_height": page.original_size[1],
                "scale_x": width / page.original_size[0] if page.original_size[0] else 1.0,
                "scale_y": height / page.original_size[1] if page.original_size[1] else 1.0,
                "tasks": task_results,
            }
            json_path = out_dir / f"{page_name}.json"
            overlay_path = out_dir / f"{page_name}-overlay.png"
            json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            _draw_overlay(image, task_results, overlay_path)
            record["json_path"] = str(json_path)
            record["overlay_path"] = str(overlay_path)
            manifest.append(record)

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote {manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
