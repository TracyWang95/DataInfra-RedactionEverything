#!/usr/bin/env python3
"""Download project models: ModelScope first, Hugging Face mirror fallback.

Usage:
  python backend/scripts/download_models.py              # all models
  python backend/scripts/download_models.py --only has
  python backend/scripts/download_models.py --only locateanything
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Prefer HF mirror when falling back from ModelScope.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# HF id -> ModelScope id (ms_id=None means no ModelScope copy; use HF mirror).
MODELS = {
    "has": {
        "hf_id": "xuanwulab/HaS_Text_0209_0.6B",
        "ms_id": None,
        "local_dir": "backend/models/has/HaS_Text_0209_0.6B",
        "ignore_patterns": ["*.gguf", "*.onnx", "*.Q4*", "*.Q8*"],
    },
    "locateanything": {
        "hf_id": "nvidia/LocateAnything-3B",
        "ms_id": "nv-community/LocateAnything-3B",
        "local_dir": "backend/models/locateanything/LocateAnything-3B-HF",
        "ignore_patterns": [],
    },
}


_ROOT: Path | None = None


def _repo_root() -> Path:
    return _ROOT or Path(__file__).resolve().parents[2]


def _download_modelscope(model_id: str, local_dir: Path) -> str:
    from modelscope import snapshot_download

    return snapshot_download(model_id, local_dir=str(local_dir))


def _download_hf(model_id: str, local_dir: Path, ignore_patterns: list[str]) -> str:
    from huggingface_hub import snapshot_download

    kwargs: dict = {"repo_id": model_id, "local_dir": str(local_dir)}
    if ignore_patterns:
        kwargs["ignore_patterns"] = ignore_patterns
    return snapshot_download(**kwargs)


def download_one(name: str, *, force: bool = False, source: str = "auto") -> Path:
    cfg = MODELS[name]
    local_dir = _repo_root() / cfg["local_dir"]
    local_dir.mkdir(parents=True, exist_ok=True)

    if not force and (local_dir / "config.json").exists():
        print(f"[{name}] SKIP already present: {local_dir}", flush=True)
        return local_dir

    ms_id = cfg.get("ms_id")
    hf_id = cfg["hf_id"]
    ignore = list(cfg.get("ignore_patterns") or [])
    errors: list[str] = []

    try_ms = source in ("auto", "modelscope") and bool(ms_id)
    try_hf = source in ("auto", "hf")

    if try_ms:
        try:
            print(f"[{name}] ModelScope -> {ms_id}", flush=True)
            path = _download_modelscope(ms_id, local_dir)
            print(f"[{name}] DONE modelscope {path}", flush=True)
            return Path(path)
        except Exception as exc:  # noqa: BLE001 — fall back to HF
            errors.append(f"modelscope: {type(exc).__name__}: {exc}")
            if source == "modelscope":
                raise RuntimeError(f"[{name}] download failed: {' | '.join(errors)}") from exc
            print(f"[{name}] ModelScope failed, fallback HF mirror: {exc}", flush=True)

    if try_hf:
        try:
            endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
            print(f"[{name}] HuggingFace ({endpoint}) -> {hf_id}", flush=True)
            path = _download_hf(hf_id, local_dir, ignore)
            print(f"[{name}] DONE hf {path}", flush=True)
            return Path(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hf: {type(exc).__name__}: {exc}")

    raise RuntimeError(f"[{name}] download failed: {' | '.join(errors) or 'no source tried'}")


def main() -> int:
    global _ROOT
    parser = argparse.ArgumentParser(description="Download models via ModelScope / HF mirror")
    parser.add_argument("--only", choices=sorted(MODELS), help="Download a single model")
    parser.add_argument(
        "--source",
        choices=["auto", "modelscope", "hf"],
        default="auto",
        help="Force download source (default: modelscope then hf)",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if present")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root for model paths (default: inferred from this script)",
    )
    args = parser.parse_args()
    if args.root is not None:
        _ROOT = args.root.resolve()

    names = [args.only] if args.only else list(MODELS)
    failed = 0
    for name in names:
        try:
            download_one(name, force=args.force, source=args.source)
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] FAIL {exc}", file=sys.stderr, flush=True)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
