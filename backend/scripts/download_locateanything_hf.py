"""Download LocateAnything-3B: ModelScope first, Hugging Face mirror fallback."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

MS_ID = "nv-community/LocateAnything-3B"
HF_ID = "nvidia/LocateAnything-3B"
FILES = [
    ".gitattributes",
    "LICENSE",
    "README.md",
    "added_tokens.json",
    "all_results.json",
    "chat_template.json",
    "config.json",
    "configuration_locateanything.py",
    "configuration_qwen2.py",
    "generate_utils.py",
    "generation_config.json",
    "image_processing_locateanything.py",
    "mask_magi_utils.py",
    "mask_sdpa_utils.py",
    "merges.txt",
    "model.safetensors.index.json",
    "modeling_locateanything.py",
    "modeling_qwen2.py",
    "modeling_vit.py",
    "preprocessor_config.json",
    "processing_locateanything.py",
    "processor_config.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.json",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
]


def _download_modelscope(local_dir: str) -> bool:
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[download] modelscope not installed, skip", flush=True)
        return False
    print(f"[download] ModelScope -> {MS_ID}", flush=True)
    path = snapshot_download(MS_ID, local_dir=local_dir)
    print(f"[done] modelscope {path}", flush=True)
    return True


def _download_hf(local_dir: str) -> None:
    from huggingface_hub import hf_hub_download

    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
    print(f"[download] HuggingFace ({endpoint}) -> {HF_ID}", flush=True)
    for filename in FILES:
        print(f"[download] {filename}", flush=True)
        path = hf_hub_download(repo_id=HF_ID, filename=filename, local_dir=local_dir)
        print(f"[done] {path}", flush=True)


if __name__ == "__main__":
    local_dir = os.environ.get(
        "LOCATE_ANYTHING_MODEL",
        "/mnt/d/has_models/LocateAnything-3B-HF",
    )
    Path(local_dir).mkdir(parents=True, exist_ok=True)
    try:
        if not _download_modelscope(local_dir):
            _download_hf(local_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] ModelScope failed ({exc}); falling back to HF mirror", flush=True)
        try:
            _download_hf(local_dir)
        except Exception as hf_exc:  # noqa: BLE001
            print(f"[fail] {hf_exc}", file=sys.stderr, flush=True)
            raise SystemExit(1) from hf_exc
    print(local_dir, flush=True)
