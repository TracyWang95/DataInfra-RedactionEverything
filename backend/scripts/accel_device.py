"""Resolve accelerator device for Ascend NPU / CUDA / CPU sidecars."""

from __future__ import annotations

import os
from typing import Any


def resolve_torch_device(prefer: str | None = None) -> str:
    """Return torch device string: npu / npu:0 / cuda / cuda:0 / cpu.

    Order when prefer is unset/auto:
      1) ASCEND_RT_VISIBLE_DEVICES or torch.npu
      2) CUDA
      3) raise (no silent CPU for large models unless ALLOW_CPU=1)
    """
    prefer = (prefer or os.environ.get("ACCEL_DEVICE") or os.environ.get("LA_DEVICE") or "auto").strip().lower()
    allow_cpu = os.environ.get("ALLOW_CPU", "").strip().lower() in {"1", "true", "yes", "on"}

    if prefer in {"cpu"}:
        if not allow_cpu:
            raise RuntimeError("CPU device requested but ALLOW_CPU is not enabled")
        return "cpu"

    import torch

    def _npu_ok() -> bool:
        try:
            import torch_npu  # noqa: F401
        except Exception as exc:
            print(f"[accel] torch_npu import failed: {exc}", flush=True)
            return False
        npu = getattr(torch, "npu", None)
        try:
            ok = bool(npu is not None and torch.npu.is_available())
        except Exception as exc:
            print(f"[accel] torch.npu.is_available failed: {exc}", flush=True)
            return False
        if not ok:
            print("[accel] torch.npu present but is_available()=False", flush=True)
        return ok

    if prefer.startswith("npu") or prefer == "ascend":
        if not _npu_ok():
            raise RuntimeError("NPU requested but torch.npu is not available")
        return prefer if prefer.startswith("npu:") else "npu"

    if prefer.startswith("cuda"):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but torch.cuda.is_available() is False")
        return prefer if ":" in prefer else "cuda"

    # auto
    if _npu_ok():
        return "npu"
    if torch.cuda.is_available():
        return "cuda"
    if allow_cpu:
        return "cpu"
    raise RuntimeError("No NPU/CUDA accelerator available (set ALLOW_CPU=1 to force CPU)")


def empty_cache(torch_mod: Any | None = None) -> None:
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    try:
        import torch

        torch_mod = torch_mod or torch
        if getattr(torch_mod, "npu", None) is not None and torch_mod.npu.is_available():
            torch_mod.npu.empty_cache()
        elif torch_mod.cuda.is_available():
            torch_mod.cuda.empty_cache()
            try:
                torch_mod.cuda.ipc_collect()
            except Exception:
                pass
    except Exception:
        pass


def is_accel_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        key in text
        for key in (
            "out of memory",
            "cudacachingallocator",
            "cuda error",
            "npu out of memory",
            "ascend",
            "huawei",
            "oom",
        )
    )
