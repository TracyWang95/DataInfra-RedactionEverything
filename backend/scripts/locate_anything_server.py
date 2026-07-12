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
from locate_anything_eval import LocateAnythingWorker, _parse_boxes, _resize_for_inference
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() not in {"", "0", "false", "no", "off"}


MODEL_NAME = os.environ.get("LOCATE_ANYTHING_MODEL_NAME", "LocateAnything-3B")
DEFAULT_MAX_SIDE = int(os.environ.get("LOCATE_ANYTHING_MAX_IMAGE_SIDE", "1280"))
DEFAULT_MIN_SIDE = int(os.environ.get("LOCATE_ANYTHING_MIN_IMAGE_SIDE", "1280"))
DEFAULT_MAX_NEW_TOKENS = int(os.environ.get("LOCATE_ANYTHING_MAX_NEW_TOKENS", "8192"))
DEFAULT_GENERATION_MODE = os.environ.get("LOCATE_ANYTHING_GENERATION_MODE", "hybrid")
DEFAULT_TEMPERATURE = float(os.environ.get("LOCATE_ANYTHING_TEMPERATURE", "0.7"))
# When set, the Qwen2 text backbone is served by vLLM (prompt-embeds) instead of
# the in-process transformers model. This server then only runs the MoonViT
# vision tower + mlp1 projector on GPU and posts the stitched embeds to vLLM.
VLLM_LM_URL = os.environ.get("LOCATE_ANYTHING_VLLM_URL", "").strip()
VLLM_LM_MODEL = os.environ.get("LOCATE_ANYTHING_VLLM_MODEL", "locate_qwen2_model")
# Fixed seed pins the 0.7/0.9 open sampling so the same page yields the same boxes
# on every click (reproducible) without collapsing to greedy. Tunable via env.
VLLM_LM_SEED = int(os.environ.get("LOCATE_ANYTHING_VLLM_SEED", "1234"))
FAST_FIRST_ENABLED = _env_flag("LOCATE_ANYTHING_FAST_FIRST", "1")
VALID_GENERATION_MODES = {"fast", "hybrid", "slow"}

# Smallest image side the adaptive-OOM retry will downscale to before giving up.
ADAPTIVE_SIDE_FLOOR = 640
# Descending candidate image sides tried on CUDA OOM (largest -> smallest).
ADAPTIVE_SIDE_LADDER = [2048, 1920, 1792, 1600, 1536, 1280, 1024]
# Cap on tokens the vLLM LM generates per detection completion.
VLLM_MAX_TOKENS = 512
# Network timeout (seconds) for a single vLLM completion request.
VLLM_REQUEST_TIMEOUT_SECONDS = 120
# Fixed confidence stamped on every LocateAnything box (model emits no score).
LOCATEANYTHING_CONFIDENCE = 0.82
# IoU at/above which two same-category boxes are treated as duplicates.
DEDUPE_IOU_THRESHOLD = 0.55
# Smaller-box containment ratio at/above which a box is dropped as a duplicate.
DEDUPE_CONTAINMENT_THRESHOLD = 0.78


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
    floor = max(ADAPTIVE_SIDE_FLOOR, min(DEFAULT_MIN_SIDE, requested))
    candidates = [requested, *ADAPTIVE_SIDE_LADDER]
    result: list[int] = []
    for side in candidates:
        side = int(side)
        if side > requested or side < floor or side in result:
            continue
        result.append(side)
    if requested not in result:
        result.insert(0, requested)
    return result


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
    response_format: dict[str, Any] | None = None


class LocateService:
    def __init__(self) -> None:
        self.worker: LocateAnythingWorker | None = None
        self.model_path = ""
        self.backend = "hf"
        self.dtype = "bfloat16"
        self.ready = False
        # Actual device the loaded weights ended up on ("cuda" / "cpu" / "" while
        # loading); /health reports this instead of a hardcoded green light.
        self.device = ""
        self.lock = asyncio.Lock()
        # vLLM-backend (prompt-embeds) state; populated by load_vision().
        self.model: Any = None
        self.processor: Any = None
        self.embed: Any = None
        self.image_token_index: int = -1
        # Tri-state for the text-only tokenization fast path (vLLM mode):
        # None = not yet verified, True = verified byte-identical to the full
        # processor output, False = differs or failed -> never used.
        self._fast_tokenize_ok: bool | None = None

    def configure(self, model_path: str, backend: str, dtype: str) -> None:
        self.model_path = model_path
        self.backend = backend
        self.dtype = dtype

    def load(self) -> None:
        if VLLM_LM_URL:
            self.load_vision()
        else:
            self.worker = LocateAnythingWorker(self.model_path, backend=self.backend, dtype_name=self.dtype)
            self.device = str(self.worker.device)
            self.ready = True

    def load_vision(self) -> None:
        """vLLM mode: keep only the MoonViT vision tower + mlp1 + embed_tokens on
        GPU and free the Qwen2 decoder (vLLM serves it). Nothing of consequence
        stays on CPU — extract_feature/mlp1 only touch the vision tower."""
        import gc

        import torch
        from transformers import AutoModel, AutoProcessor

        self.processor = AutoProcessor.from_pretrained(self.model_path, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            self.model_path, dtype=torch.bfloat16, trust_remote_code=True, low_cpu_mem_usage=True
        ).eval()
        model.vision_model.to("cuda")
        model.mlp1.to("cuda")
        self.embed = model.language_model.model.embed_tokens.to("cuda")
        self.image_token_index = int(model.image_token_index)
        # Release the 36 idle decoder layers + lm_head from CPU RAM (~5GB). The
        # embed_tokens module is already referenced by self.embed (on GPU), so it
        # survives; the language_model shell/config is kept for safety.
        model.language_model.model.layers = torch.nn.ModuleList()
        model.language_model.lm_head = torch.nn.Identity()
        gc.collect()
        self.model = model
        # MoonViT's bundled SDPA builds a dense [1,N,N] attention mask even for a
        # single image, which forces F.scaled_dot_product_attention onto its slow
        # math/mem-efficient backend. For one image (one sequence) that mask is
        # all-True (redundant); passing attn_mask=None hits the fast fused kernel.
        # Output is identical, only the kernel changes. flash_attn is not installed,
        # so MoonViT otherwise runs this masked fallback on every page (~1.7s encode).
        try:
            import sys as _sys

            import torch.nn.functional as _F  # noqa: N812

            _vmod = _sys.modules.get(type(model.vision_model).__module__)
            _funcs = getattr(_vmod, "VL_VISION_ATTENTION_FUNCTIONS", None)
            if isinstance(_funcs, dict):
                def _fast_sdpa(q, k, v, q_cu_seqlens=None, k_cu_seqlens=None):
                    qt, kt, vt = q.transpose(0, 1), k.transpose(0, 1), v.transpose(0, 1)
                    if q_cu_seqlens is None or len(q_cu_seqlens) <= 2:
                        attn_mask = None  # single image: full attention, fast fused kernel
                    else:
                        seq = q.shape[0]
                        attn_mask = torch.zeros([1, seq, seq], device=q.device, dtype=torch.bool)
                        for i in range(1, len(q_cu_seqlens)):
                            attn_mask[..., q_cu_seqlens[i - 1]:q_cu_seqlens[i], q_cu_seqlens[i - 1]:q_cu_seqlens[i]] = True
                    out = _F.scaled_dot_product_attention(qt, kt, vt, attn_mask, dropout_p=0.0)
                    return out.transpose(0, 1).reshape(q.shape[0], -1)

                _funcs["sdpa"] = _fast_sdpa
                _vmod.sdpa_attention = _fast_sdpa  # flash fallback calls this global by name
                print("[LocateAnything] MoonViT fast-SDPA (maskless single-image) patch applied", flush=True)
        except Exception as exc:
            print(f"[LocateAnything] MoonViT fast-SDPA patch skipped: {exc}", flush=True)
        print(f"[LocateAnything] vLLM mode: vision tower on GPU, LM served by {VLLM_LM_URL}", flush=True)
        self.device = "cuda"  # the .to("cuda") calls above would have raised otherwise
        self.ready = True

    def _encode_vit(self, image: Image.Image):
        """Run the MoonViT vision tower once and return the projected image
        embeddings plus this image's placeholder token count. Both depend only
        on the image, so they can be reused across many category prompts (the
        text part of the prompt does not change them)."""
        import numpy as np
        import torch

        messages = [
            {"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": "locate"}]}
        ]
        text = self.processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = self.processor.process_vision_info(messages)
        inputs = self.processor(text=[text], images=images, videos=videos, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to("cuda", torch.bfloat16)
        ig = inputs.get("image_grid_hws", None)
        # Mirror of replace_media_placeholder's token count for a single image:
        # int(h * w) // (merge_kernel_size[0] * merge_kernel_size[1]).
        num_image_tokens = 0
        if ig is not None and len(ig) > 0:
            mk = self.processor.image_processor.merge_kernel_size
            num_image_tokens = int(ig[0][0] * ig[0][1]) // (mk[0] * mk[1])
        if isinstance(ig, np.ndarray):
            ig = torch.from_numpy(ig)
        if ig is not None:
            ig = ig.to("cuda", torch.int32)
        with torch.no_grad():
            vit = self.model.extract_feature(pixel_values, ig)
            if isinstance(vit, list):
                vit = torch.cat(vit, dim=0)
            elif ig is not None:
                vit = torch.cat(vit, dim=0)
            vit = self.model.mlp1(vit)
        return vit, num_image_tokens

    def _full_input_ids(self, image: Image.Image, prompt: str):
        """input_ids exactly as the full processor produces them (re-runs the
        image preprocessing; slow but canonical)."""
        messages = [
            {"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}
        ]
        text = self.processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = self.processor.process_vision_info(messages)
        inputs = self.processor(text=[text], images=images, videos=videos, return_tensors="pt")
        return inputs["input_ids"]

    def _fast_input_ids(self, prompt: str, num_image_tokens: int):
        """Text-only reconstruction of the processor's input_ids: expand the
        <image-1> placeholder with the cached per-image token count and tokenize
        with the processor's text kwargs (padding=False). This skips the
        per-prompt image re-preprocessing the full processor call would repeat.
        Only trusted after _prompt_input_ids verified it byte-identical."""
        proc = self.processor
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = proc.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        # Bail out on anything but the expected single-image layout (e.g. a
        # prompt that itself contains media placeholders); the caller then falls
        # back to the canonical full-processor path.
        if text.count(f"<{proc.image_placeholder}-") != 1 or f"<{proc.video_placeholder}-" in text:
            raise ValueError("unexpected media placeholder layout")
        expansion = (
            f"<image 1>{proc.image_start_token}"
            f"{proc.image_token * num_image_tokens}{proc.image_end_token}"
        )
        expanded = text.replace(f"<{proc.image_placeholder}-1>", expansion, 1)
        return proc.tokenizer([expanded], padding=False, return_tensors="pt")["input_ids"]

    def _prompt_input_ids(self, image: Image.Image, prompt: str, num_image_tokens: int):
        """input_ids for (image, prompt). The fast path is only used after a
        one-time byte-identical comparison against the full processor output;
        any difference (or error) disables it permanently, so output can never
        drift from the current behavior."""
        import torch

        if self._fast_tokenize_ok and num_image_tokens > 0:
            try:
                return self._fast_input_ids(prompt, num_image_tokens)
            except Exception:
                pass  # fall back to the canonical path below
        full_ids = self._full_input_ids(image, prompt)
        if self._fast_tokenize_ok is None and num_image_tokens > 0:
            try:
                fast_ids = self._fast_input_ids(prompt, num_image_tokens)
                self._fast_tokenize_ok = bool(
                    full_ids.shape == fast_ids.shape and torch.equal(full_ids, fast_ids)
                )
                state = "verified byte-identical" if self._fast_tokenize_ok else "MISMATCH; disabled"
                print(f"[LocateAnything] fast tokenization {state}", flush=True)
            except Exception as exc:
                self._fast_tokenize_ok = False
                print(f"[LocateAnything] fast tokenization unavailable: {exc}", flush=True)
        return full_ids

    def _build_prompt_embeds_b64(self, image: Image.Image, prompt: str, vit, num_image_tokens: int) -> str:
        """Stitch the precomputed image embeds (vit) into the text-embed sequence
        for `prompt` and serialize to base64 for vLLM prompt-embeds."""
        import base64
        import io

        import torch

        input_ids = self._prompt_input_ids(image, prompt, num_image_tokens).to("cuda")
        with torch.no_grad():
            emb = self.embed(input_ids).to(torch.bfloat16)
            B, N, C = emb.shape
            emb = emb.reshape(B * N, C)
            idf = input_ids.reshape(B * N)
            sel = idf == self.image_token_index
            emb[sel] = vit.reshape(-1, C).to(emb.dtype)
            emb = emb.reshape(B, N, C)
        prompt_embeds = emb.squeeze(0).contiguous().to("cpu", torch.bfloat16)
        buf = io.BytesIO()
        torch.save(prompt_embeds, buf)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _vllm_complete_b64(self, prompt_embeds_b64: str) -> str:
        """Greedy vLLM completion from a base64 prompt-embeds payload."""
        import json
        import urllib.error
        import urllib.request

        body = {
            "model": VLLM_LM_MODEL,
            "max_tokens": VLLM_MAX_TOKENS,
            # Open sampling (temp 0.7 / top_p 0.9), matching the upstream NVIDIA
            # demo. Open decoding explores more candidate regions and recalls
            # multi-instance targets (e.g. several seals) that greedy collapses
            # away — recall is the priority here. The cost is that results vary
            # slightly between runs; that is intentional. NOTE: repetition_penalty
            # is omitted — with vLLM prompt-embeds there are no prompt token-ids, so
            # the penalty kernel indexes out of bounds and triggers a CUDA assert.
            "temperature": DEFAULT_TEMPERATURE,
            "top_p": 0.9,
            "seed": VLLM_LM_SEED,
            "prompt_embeds": prompt_embeds_b64,
            "skip_special_tokens": False,
            "spaces_between_special_tokens": False,
        }
        req = urllib.request.Request(
            VLLM_LM_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=VLLM_REQUEST_TIMEOUT_SECONDS) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            # URLError covers HTTPError (subclass); TimeoutError covers socket
            # read timeouts that urlopen raises unwrapped.
            raise HTTPException(
                status_code=503, detail=f"LocateAnything LM backend unavailable: {exc}"
            ) from exc
        return payload["choices"][0]["text"]

    async def _predict_boxes_vllm(
        self, image: Image.Image, prompt: str, max_image_side: int
    ) -> tuple[str, list[dict[str, Any]], tuple[int, int]]:
        if not self.ready:
            raise HTTPException(status_code=503, detail="LocateAnything model is not ready")
        inference_image = _resize_for_inference(image, max_image_side)
        # GPU work (vision encode + embed stitch) stays inside the lock; the
        # vLLM network round-trip (up to VLLM_REQUEST_TIMEOUT_SECONDS) runs
        # outside it so a slow generation cannot starve other GPU requests --
        # same structure as predict_boxes_per_category.
        async with self.lock:
            try:
                vit, num_image_tokens = await asyncio.to_thread(self._encode_vit, inference_image)
                b64 = await asyncio.to_thread(
                    self._build_prompt_embeds_b64, inference_image, prompt, vit, num_image_tokens
                )
            except RuntimeError as exc:
                if _is_cuda_capacity_error(exc):
                    raise HTTPException(
                        status_code=503,
                        detail=f"LocateAnything CUDA capacity exhausted during vision encode: {exc}",
                    ) from exc
                raise
            finally:
                # Same hygiene as worker-mode predict (trim after every pass, not
                # only on failure): per-image activation buffers otherwise stay in
                # the allocator cache and grow the process across requests until
                # the shared 16GB card thrashes (observed: tower at ~12GB, encodes
                # stalling at 100% GPU with the whole stack resident).
                trim_cuda_cache("vllm-chat-encode")
        answer = await asyncio.to_thread(self._vllm_complete_b64, b64)
        boxes = _parse_boxes(answer, inference_image.width, inference_image.height)
        return answer, boxes, (inference_image.width, inference_image.height)

    async def predict_boxes_per_category(
        self, image: Image.Image, categories: list[str], max_image_side: int = DEFAULT_MAX_SIDE
    ) -> tuple[list[tuple[str, list[dict[str, Any]]]], tuple[int, int], str]:
        """vLLM-mode multi-category detect with full recall.

        LocateAnything's multi-instance recall collapses when many categories
        share one prompt (e.g. 21 categories -> 0 seals, 1 category -> 4 seals),
        so we run each category as its own single-category prompt. The expensive
        MoonViT vision pass runs ONCE; the cheap vLLM generations are then issued
        concurrently (the LM server batches them), keeping latency ~ one encode
        plus a few batched generations rather than N full passes.
        """
        if not self.ready:
            raise HTTPException(status_code=503, detail="LocateAnything model is not ready")
        inference_image = _resize_for_inference(image, max_image_side)
        width, height = inference_image.width, inference_image.height
        _t0 = time.perf_counter()
        # Phase 1 (GPU, serialized): one vision encode + per-category prompt-embeds.
        async with self.lock:
            try:
                vit, num_image_tokens = await asyncio.to_thread(self._encode_vit, inference_image)
                _t_enc = time.perf_counter()
                payloads: list[tuple[str, str]] = []
                for cat in categories:
                    b64 = await asyncio.to_thread(
                        self._build_prompt_embeds_b64, inference_image, _detect_prompt([cat]), vit, num_image_tokens
                    )
                    payloads.append((cat, b64))
                _t_build = time.perf_counter()
            except RuntimeError as exc:
                if _is_cuda_capacity_error(exc):
                    raise HTTPException(
                        status_code=503,
                        detail=f"LocateAnything CUDA capacity exhausted during vision encode: {exc}",
                    ) from exc
                raise
            finally:
                # Mirror worker-mode predict: trim the allocator cache after every
                # encode pass so per-image activations cannot accumulate (see
                # _predict_boxes_vllm for the observed thrash this prevents).
                trim_cuda_cache("vllm-detect-encode")

        # Phase 2 (network, concurrent): vLLM generations batch on the LM server.
        async def _gen(cat: str, b64: str) -> tuple[str, list[dict[str, Any]], str]:
            answer = await asyncio.to_thread(self._vllm_complete_b64, b64)
            return cat, _parse_boxes(answer, width, height), answer

        results = await asyncio.gather(*[_gen(cat, b64) for cat, b64 in payloads])
        print(
            f"[LA-timing] cats={len(categories)} size={width}x{height} "
            f"encode={_t_enc - _t0:.2f}s build={_t_build - _t_enc:.2f}s "
            f"generate={time.perf_counter() - _t_build:.2f}s total={time.perf_counter() - _t0:.2f}s",
            flush=True,
        )
        per_category = [(cat, boxes) for cat, boxes, _ in results]
        raw = "\n".join(f"[{cat}] {answer}" for cat, _, answer in results)
        return per_category, (width, height), raw

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
        if VLLM_LM_URL:
            return await self._predict_boxes_vllm(image, prompt, max_image_side)
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
        # exif_transpose/convert force-decode the pixel data, which is where a
        # truncated/corrupt payload actually fails -- still a client error (400).
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image") from exc
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
    """SHORT category phrase per the official CATEGORIES semantics (model
    card: detection takes a comma-separated category list). The old variant
    concatenated every Check/Exclude checklist row into one verbose
    description — exactly the negative-laden prompt the A/B measured to
    suppress faint detections. The backend now sends an explicit "Query:"
    line per type (checklist row.query or the human name); fall back to the
    name= field, then the prettified id."""
    escaped = re.escape(type_id)
    block_match = re.search(
        rf"type_id={escaped};.*?(?=\n-\s*type_id=|\nIf none,|\Z)",
        prompt,
        flags=re.S,
    )
    if block_match:
        query_match = re.search(r"^\s*Query:\s*(.+)$", block_match.group(0), flags=re.M)
        if query_match and query_match.group(1).strip():
            return query_match.group(1).strip()
    name_match = re.search(rf"type_id={escaped};\s*name=([^\n\r]+)", prompt)
    if name_match and name_match.group(1).strip():
        return name_match.group(1).strip()
    return type_id.replace("_", " ")


def _chat_prompt_for_type(prompt: str, type_id: str) -> str:
    """Grounding prompt for ONE allowed type_id — the uniform path for every
    category, signature included. The old "签"/"signature" keyword hijack
    rerouted the WHOLE request to a signature preset, so any second custom
    type was never detected and a stray 签 in a name like 签收单/标签 dropped
    every box. Keep the description short: the verbose negative-laden variant
    made the model emit <box>None</box> on faint signatures (1.tiff doctor
    signature) while a short description recovers them."""
    description = _description_for_type_id(prompt, type_id)
    return f"Locate all the instances that matches the following description: {description}."


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
    # Match the upstream LocateAnything demo prompt verbatim: a single
    # "Locate all the instances that matches the following description: ..." line
    # with the per-category descriptions joined by </c>. The previous multi-line
    # variant embedded a literal "<ref>signature</ref>" example that the model
    # echoed back (returning a lone signature box instead of the seals), and its
    # verbose negatives suppressed real detections.
    # The request text IS the grounding description — the backend sends the
    # user's 识别清单 wording (or its factory default) verbatim; legacy slug
    # callers get their underscores prettified into spaces.
    descriptions = [
        _normalize_slug(raw).replace("_", " ") for raw in categories if str(raw or "").strip()
    ]
    category_set_str = "</c>".join(descriptions)
    return f"Locate all the instances that matches the following description: {category_set_str}."


def _box_to_normalized(box: dict[str, Any], width: int, height: int, category: str) -> dict[str, Any] | None:
    x = max(0.0, min(1.0, float(box["x"]) / max(1, width)))
    y = max(0.0, min(1.0, float(box["y"]) / max(1, height)))
    w = max(0.0, min(1.0 - x, float(box["width"]) / max(1, width)))
    h = max(0.0, min(1.0 - y, float(box["height"]) / max(1, height)))
    if not _accept_normalized_box(category, x, y, w, h):
        return None
    return {"x": x, "y": y, "width": w, "height": h, "category": category, "confidence": LOCATEANYTHING_CONFIDENCE}


def _accept_normalized_box(category: str, x: float, y: float, w: float, h: float) -> bool:
    # Trust LA completely: detections are kept exactly as the model returns them.
    # No thresholds, no magic numbers, no per-category geometry. The only thing
    # rejected is a mathematically degenerate box (non-positive area) — that is
    # malformed output, not a detection.
    return w > 0 and h > 0


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
            if any(
                _box_iou(item, existing) >= DEDUPE_IOU_THRESHOLD
                or _box_containment(item, existing) >= DEDUPE_CONTAINMENT_THRESHOLD
                for existing in kept
            ):
                continue
            kept.append(item)
        kept_all.extend(kept)
    return sorted(kept_all, key=lambda item: (item.get("category", ""), float(item["y"]), float(item["x"])))


@app.on_event("startup")
async def startup() -> None:
    print(f"[LocateAnything] loading model={service.model_path}", flush=True)
    await asyncio.to_thread(service.load)
    print("[LocateAnything] ready", flush=True)


@app.get("/health")
async def health() -> dict[str, Any]:
    # Honest report: real CUDA availability and the device the weights actually
    # loaded on, instead of hardcoded green lights.
    try:
        import torch

        gpu_available = bool(torch.cuda.is_available())
    except Exception:
        gpu_available = False
    if service.ready:
        runtime_mode = "gpu" if str(service.device).startswith("cuda") else "cpu"
    else:
        # Still loading: report the device the GPU-only load is targeting.
        runtime_mode = "gpu" if gpu_available else "cpu"
    return {
        "status": "ok" if service.ready else "loading",
        "ready": service.ready,
        "model": MODEL_NAME,
        "runtime": "transformers-locateanything",
        "runtime_mode": runtime_mode,
        "gpu_available": gpu_available,
        "device": service.device or "unknown",
        "gpu_only_mode": True,
        "cpu_fallback_risk": runtime_mode != "gpu",
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
    max_new_tokens = max(int(req.max_tokens or 0), DEFAULT_MAX_NEW_TOKENS)
    temperature = float(req.temperature if req.temperature is not None else DEFAULT_TEMPERATURE)
    # Structured-output contract: the backend checklist caller asks for JSON via
    # the standard OpenAI response_format field. The prompt-literal sniff stays as
    # a fallback for older backends — the sole real JSON sender (_checklist_prompt)
    # always carries "Schema:" and "Allowed type_id:".
    wants_json = (
        str((req.response_format or {}).get("type") or "") == "json_object"
        or "Schema:" in prompt
        or "Allowed type_id:" in prompt
        or '"objects"' in prompt
    )
    if wants_json:
        # One grounding pass per allowed type_id: every configured type is
        # detected and its boxes tagged by the type they were REQUESTED as — no
        # first-type-only shortcut, no keyword-based prompt hijack.
        normalized_objects: list[dict[str, Any]] = []
        for type_id in allowed_ids or ["object"]:
            _answer, boxes, (width, height) = await service.predict_boxes(
                image,
                _chat_prompt_for_type(prompt, type_id),
                max_new_tokens=max_new_tokens,
                temperature=temperature,
            )
            for box in boxes:
                normalized = _box_to_normalized(box, width, height, type_id)
                if normalized is not None:
                    normalized_objects.append(normalized)
        normalized_objects = _dedupe_boxes(normalized_objects)
        objects = [
            {
                "type_id": box["category"],
                "label": box["category"],
                "box_2d": [
                    max(0, min(1000, round(float(box["x"]) * 1000))),
                    max(0, min(1000, round(float(box["y"]) * 1000))),
                    max(0, min(1000, round((float(box["x"]) + float(box["width"])) * 1000))),
                    max(0, min(1000, round((float(box["y"]) + float(box["height"])) * 1000))),
                ],
                "confidence": LOCATEANYTHING_CONFIDENCE,
                "rule_matched": f"{box['category']}#locateanything",
                "text": str(box["category"]),
            }
            for box in normalized_objects
        ]
        content = json.dumps({"objects": objects}, ensure_ascii=False, separators=(",", ":"))
    else:
        type_id = allowed_ids[0] if allowed_ids else "object"
        content, _boxes, _size = await service.predict_boxes(
            image,
            _chat_prompt_for_type(prompt, type_id),
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
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
    # Every tag is grounded verbatim — the backend owns the wording (the
    # user's 识别清单 or its factory default, see SLUG_TO_DEFAULT_QUERY there);
    # this server holds no prompt table. Non-ASCII (中文) tags flow through.
    requested = [_normalize_slug(item) for item in (req.categories or [])]
    requested = list(dict.fromkeys(item for item in requested if item))
    if not requested:
        return {"boxes": [], "elapsed": 0.0, "model": MODEL_NAME}
    start = time.perf_counter()
    raw_answers: list[str] = []
    out: list[dict[str, Any]] = []
    # Signature is now detected like every other visual category (per-category
    # path). The old special-case tiling fallback mislocalized large/stylized
    # signatures (boxing nearby seal/printed text); unifying it gives consistent
    # behavior and lets the signature acceptance filter reject bad boxes instead
    # of forcing a misplaced one.
    general_requested = list(requested)

    if general_requested:
        if VLLM_LM_URL:
            # vLLM mode: one prompt per category (multi-category recall collapses),
            # sharing a single vision encode. Boxes come back tagged by category.
            per_category, (width, height), raw = await service.predict_boxes_per_category(
                image, general_requested, max_image_side=req.max_image_side or DEFAULT_MAX_SIDE
            )
            raw_answers.append(raw)
            for category, boxes in per_category:
                for box in boxes:
                    normalized = _box_to_normalized(box, width, height, category)
                    if normalized is not None:
                        out.append(normalized)
        else:
            # Per-category prompts: LocateAnything multi-instance recall collapses
            # when several categories share one prompt (observed: {official_seal,
            # signature} together -> 1 signature, signature alone -> 3). One
            # single-category hybrid pass each restores recall. Mirrors the vLLM
            # predict_boxes_per_category path. Quality over a few extra seconds.
            for cat in general_requested:
                answer, boxes, (width, height) = await service.predict_boxes(image, _detect_prompt([cat]))
                raw_answers.append(f"[{cat}] {answer}")
                for box in boxes:
                    normalized = _box_to_normalized(box, width, height, cat)
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
