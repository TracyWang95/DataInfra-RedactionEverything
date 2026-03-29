"""一次性下载 HaS Image YOLO 权重到 backend/models/has_image/（仓库 .gitignore 已忽略 models）。"""
from __future__ import annotations

import os
import sys

REPO_ID = "xuanwulab/HaS_Image_0209_FP32"
FILENAME = "sensitive_seg_best.pt"


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dest_dir = os.path.join(root, "backend", "models", "has_image")
    os.makedirs(dest_dir, exist_ok=True)
    out_path = os.path.join(dest_dir, FILENAME)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 1_000_000:
        print(f"[ok] 已存在: {out_path}")
        return 0
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("请先: pip install huggingface_hub", file=sys.stderr)
        return 1
    print(f"下载 {REPO_ID} / {FILENAME} -> {dest_dir} ...")
    p = hf_hub_download(repo_id=REPO_ID, filename=FILENAME, local_dir=dest_dir)
    print(f"[ok] {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
