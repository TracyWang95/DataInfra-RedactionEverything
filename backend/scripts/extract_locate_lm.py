"""One-time surgery: split LocateAnything-3B-HF into a vLLM-servable Qwen2 LM
plus a standalone embed_tokens table.

The vLLM path (WuNein/LocateAnything-vLLM) runs the MoonViT vision tower +
mlp1 projector locally (transformers) and serves only the Qwen2 text backbone
on vLLM via --enable-prompt-embeds. This script produces that text backbone.

Run on CPU so it does not contend with the live GPU services:
    python backend/scripts/extract_locate_lm.py \
        --src /mnt/d/has_models/LocateAnything-3B-HF \
        --out /mnt/d/has_models/locate_qwen2_model
"""

from __future__ import annotations

import argparse
import json
import os

import torch
from safetensors.torch import save_file
from transformers import AutoModel, AutoTokenizer


def main() -> int:
    parser = argparse.ArgumentParser()
    # Defaults are overridable via the same env vars the runtime uses (.env
    # LOCATE_ANYTHING_MODEL / LOCATE_ANYTHING_LM_MODEL_DIR); fallback values
    # match this machine's layout.
    parser.add_argument("--src", default=os.environ.get("LOCATE_ANYTHING_MODEL", "/mnt/d/has_models/LocateAnything-3B-HF"))
    parser.add_argument("--out", default=os.environ.get("LOCATE_ANYTHING_LM_MODEL_DIR", "/mnt/d/has_models/locate_qwen2_model"))
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"[extract] loading tokenizer from {args.src}", flush=True)
    tok = AutoTokenizer.from_pretrained(args.src, trust_remote_code=True)

    print("[extract] loading full model on CPU (bfloat16)...", flush=True)
    model = AutoModel.from_pretrained(
        args.src,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model.eval()

    image_token_index = int(getattr(model, "image_token_index", getattr(model.config, "image_token_index", -1)))
    print(f"[extract] image_token_index={image_token_index}", flush=True)

    print(f"[extract] saving language_model -> {args.out}", flush=True)
    model.language_model.save_pretrained(args.out, safe_serialization=True)
    tok.save_pretrained(args.out)

    embed = model.language_model.model.embed_tokens.weight.detach().cpu().contiguous()
    save_file({"weight": embed}, os.path.join(args.out, "qwen2_embed_tokens.safetensors"))
    print(f"[extract] embed_tokens saved, shape={tuple(embed.shape)}", flush=True)

    # Record the runtime constants the vision server needs, so it never has to
    # re-derive them from the (large) full model.
    meta = {
        "image_token_index": image_token_index,
        "box_start_token_id": int(getattr(model.config, "box_start_token_id", 151668)),
        "ref_start_token_id": int(getattr(model.config, "ref_start_token_id", 151672)),
        "hidden_size": int(model.language_model.config.hidden_size),
        "vocab_size": int(model.language_model.config.vocab_size),
    }
    with open(os.path.join(args.out, "locate_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[extract] wrote locate_meta.json: {meta}", flush=True)
    print("[extract] done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
