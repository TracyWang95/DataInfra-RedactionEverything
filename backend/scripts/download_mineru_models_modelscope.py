#!/usr/bin/env python3
"""
从 ModelScope 将 MinerU pipeline 依赖（OpenDataLab/PDF-Extract-Kit-1.0）下载到本地目录，
与 MinerU 官方 mineru-models-download pipeline 逻辑一致，便于离线运行 OCR 微服务。

默认保存路径: <backend>/models/mineru（与 ocr_server 自动检测一致）

用法（在 backend 目录下）:
  python scripts/download_mineru_models_modelscope.py

或指定目录:
  MINERU_PIPELINE_LOCAL_DIR=/path/to/dir python scripts/download_mineru_models_modelscope.py

下载完成后重启 ocr_server；若目录下已有 models/，服务会自动使用 MINERU_MODEL_SOURCE=local。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    os.environ.setdefault("MODELSCOPE_DOMAIN", "www.modelscope.cn")

    backend = _backend_root()
    default_dest = backend / "models" / "mineru"
    raw = os.environ.get("MINERU_PIPELINE_LOCAL_DIR", "").strip()
    dest = Path(raw).resolve() if raw else default_dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    # MinerU 包内枚举与下载列表
    sys.path.insert(0, str(backend))
    try:
        from modelscope import snapshot_download
        from mineru.utils.enum_class import ModelPath
    except ImportError as e:
        print(
            "导入失败（需要已安装 mineru、modelscope）:",
            e,
            file=sys.stderr,
            flush=True,
        )
        return 1

    repo = ModelPath.pipeline_root_modelscope
    paths = [
        ModelPath.pp_doclayout_v2,
        ModelPath.unimernet_small,
        ModelPath.pytorch_paddle,
        ModelPath.slanet_plus,
        ModelPath.unet_structure,
        ModelPath.paddle_table_cls,
        ModelPath.paddle_orientation_classification,
        ModelPath.pp_formulanet_plus_m,
    ]

    last_root = ""
    print(f"[MinerU] ModelScope 仓库: {repo}", flush=True)
    print(f"[MinerU] 目标目录: {dest}", flush=True)

    for rel in paths:
        p = rel.strip("/")
        print(f"[MinerU] 下载片段: {p}", flush=True)
        last_root = snapshot_download(
            repo,
            local_dir=str(dest),
            allow_patterns=[p, f"{p}/*"],
        )

    print("[MinerU] 完成。快照根路径:", last_root, flush=True)
    if not (dest / "models").is_dir():
        print(
            "[MinerU] 警告: 未在目标目录下发现 models/，请检查下载是否完整。",
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(
        "[MinerU] 请重启 ocr_server；若路径为默认目录，将自动启用本地模型（无需额外配置）。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
