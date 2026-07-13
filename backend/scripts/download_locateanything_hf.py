from __future__ import annotations

import os

from huggingface_hub import hf_hub_download

if __name__ == "__main__":
    repo_id = "nvidia/LocateAnything-3B"
    # Same env var the runtime uses (.env LOCATE_ANYTHING_MODEL); the default
    # matches this machine's layout.
    local_dir = os.environ.get("LOCATE_ANYTHING_MODEL", "/mnt/d/has_models/LocateAnything-3B-HF")
    files = [
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
    for filename in files:
        print(f"[download] {filename}", flush=True)
        path = hf_hub_download(repo_id=repo_id, filename=filename, local_dir=local_dir)
        print(f"[done] {path}", flush=True)
    print(local_dir, flush=True)
