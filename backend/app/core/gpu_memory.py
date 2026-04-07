# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
GPU 显存查询模块
支持 nvidia-smi / pynvml / PaddlePaddle 三种方式查询 GPU 显存占用。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_nvml_initialized: bool = False
_nvml_dll_prepared: bool = False


# ---------------------------------------------------------------------------
# nvidia-smi helpers
# ---------------------------------------------------------------------------

def _nvsmi_install_dirs_windows() -> list[str]:
    """NVIDIA NVSMI 目录（nvidia-smi.exe 与 nvml.dll 常同目录；多盘符/多安装位）。"""
    out: list[str] = []
    seen: set[str] = set()
    if os.name != "nt":
        return out
    for key in ("LEGAL_REDACTION_NVSMI_PATH", "NVIDIA_NVSMI_PATH"):
        p = os.environ.get(key, "").strip().strip('"')
        if p and os.path.isdir(p) and p not in seen:
            seen.add(p)
            out.append(p)
    roots: list[str] = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32"),
    ]
    for letter in ("D", "E", "F"):
        roots.append(f"{letter}:\\Program Files")
    for root in roots:
        p = os.path.join(root, "NVIDIA Corporation", "NVSMI")
        if p not in seen and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    pd = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "NVIDIA Corporation", "NVSMI")
    if pd not in seen and os.path.isdir(pd):
        seen.add(pd)
        out.append(pd)
    return out


def _nvidia_smi_executable_candidates() -> list[str]:
    """
    可执行文件路径候选。
    Windows 下 IDE/服务启动的 Python 往往没有用户终端里的 PATH，故 **优先** 固定 NVSMI 路径。
    """
    out: list[str] = []
    seen: set[str] = set()
    if os.name == "nt":
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        for extra in (
            os.path.join(sysroot, "System32", "nvidia-smi.exe"),
            os.path.join(sysroot, "nvidia-smi.exe"),
        ):
            if extra not in seen and os.path.isfile(extra):
                seen.add(extra)
                out.append(extra)
        for d in _nvsmi_install_dirs_windows():
            p = os.path.join(d, "nvidia-smi.exe")
            if p not in seen and os.path.isfile(p):
                seen.add(p)
                out.append(p)
    for name in ("nvidia-smi", "nvidia-smi.exe"):
        w = shutil.which(name)
        if w and w not in seen and os.path.isfile(w):
            seen.add(w)
            out.append(w)
    return out


def _parse_nvidia_smi_memory_csv(stdout: str) -> dict | None:
    if not stdout or not stdout.strip():
        return None
    line = stdout.strip().splitlines()[0].lstrip("\ufeff")
    parts = [x.strip() for x in line.split(",")]
    if len(parts) < 2:
        return None
    try:
        used_mb = int(float(parts[0]))
        total_mb = int(float(parts[1]))
        return {"used_mb": used_mb, "total_mb": total_mb}
    except (ValueError, TypeError):
        return None


def _parse_nvidia_smi_loose(stdout: str) -> dict | None:
    """兼容非英文环境或表格输出：匹配「数字 MiB / 数字 MiB」。"""
    if not stdout:
        return None
    m = re.search(r"(\d+)\s*MiB\s*/\s*(\d+)\s*MiB", stdout, re.IGNORECASE)
    if not m:
        return None
    try:
        return {"used_mb": int(m.group(1)), "total_mb": int(m.group(2))}
    except (ValueError, TypeError):
        return None


def _run_one_nvidia_smi(
    exe: str,
    *,
    use_no_window: bool,
    cwd: str | None = None,
    loose_fallback: bool = False,
) -> dict | None:
    """单次运行 nvidia-smi；cwd 设为 exe 所在目录可加载同目录 nvml.dll（Windows 常见问题）。"""
    args = [exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]
    timeout = 12.0
    workdir = cwd
    if workdir is None and os.name == "nt":
        workdir = os.path.dirname(os.path.abspath(exe)) or None

    base_kw: dict = {
        "capture_output": True,
        "timeout": timeout,
        "encoding": "utf-8",
        "errors": "replace",
        "stdin": subprocess.DEVNULL,
    }
    if workdir and os.path.isdir(workdir):
        base_kw["cwd"] = workdir
    if os.name == "nt" and use_no_window:
        base_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _parse(out: str) -> dict | None:
        p = _parse_nvidia_smi_memory_csv(out)
        if p:
            return p
        if loose_fallback:
            return _parse_nvidia_smi_loose(out)
        return None

    try:
        r = subprocess.run(args, **base_kw)
        out = (r.stdout or "").strip()
        if not out and (r.stderr or "").strip():
            out = (r.stderr or "").strip()
        parsed = _parse(out)
        if parsed and r.returncode == 0:
            return parsed
        if parsed and out:
            return parsed
        # 无 CSV 时再试整表输出（部分驱动/语言包下 query 失败）
        if loose_fallback and not parsed:
            kw2: dict = {
                "capture_output": True,
                "timeout": timeout,
                "encoding": "utf-8",
                "errors": "replace",
                "stdin": subprocess.DEVNULL,
            }
            if workdir and os.path.isdir(workdir):
                kw2["cwd"] = workdir
            if os.name == "nt" and use_no_window:
                kw2["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            r2 = subprocess.run([exe], **kw2)
            out2 = ((r2.stdout or "") + "\n" + (r2.stderr or "")).strip()
            parsed2 = _parse_nvidia_smi_loose(out2)
            if parsed2:
                return parsed2
    except (subprocess.SubprocessError, OSError, ValueError, TypeError):
        pass
    return None


def _query_gpu_memory_nvidia_smi() -> dict | None:
    """
    本机 NVIDIA 显存占用（MiB）。无 nvidia-smi 或非 NVIDIA 环境返回 None。
    """
    for exe in _nvidia_smi_executable_candidates():
        for m in (
            _run_one_nvidia_smi(exe, use_no_window=True, loose_fallback=False),
            _run_one_nvidia_smi(exe, use_no_window=False, loose_fallback=False),
            _run_one_nvidia_smi(exe, use_no_window=False, loose_fallback=True),
        ):
            if m:
                return m
    return None


# ---------------------------------------------------------------------------
# pynvml helpers
# ---------------------------------------------------------------------------

def _ensure_nvml_dll_windows() -> None:
    """Python 3.8+ Windows：nvml.dll 在 NVSMI 目录时须 add_dll_directory，否则 pynvml 初始化失败。"""
    global _nvml_dll_prepared
    if _nvml_dll_prepared or os.name != "nt":
        return
    _nvml_dll_prepared = True
    path_prefix = []
    for d in _nvsmi_install_dirs_windows():
        nvml = os.path.join(d, "nvml.dll")
        if os.path.isfile(nvml):
            try:
                if sys.version_info >= (3, 8):
                    os.add_dll_directory(d)
            except (OSError, AttributeError):
                pass
            path_prefix.append(d)
    if path_prefix:
        os.environ["PATH"] = os.pathsep.join(path_prefix) + os.pathsep + os.environ.get("PATH", "")


def _query_gpu_memory_pynvml() -> dict | None:
    """NVML（与 nvidia-smi 同源）；Windows 上先注入 NVSMI 目录再 nvmlInit。"""
    global _nvml_initialized
    try:
        import pynvml
    except ImportError:
        return None
    if os.name == "nt":
        _ensure_nvml_dll_windows()
    try:
        if not _nvml_initialized:
            pynvml.nvmlInit()
            _nvml_initialized = True
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        mib = 1024 * 1024
        return {"used_mb": int(mem.used // mib), "total_mb": max(1, int(mem.total // mib))}
    except Exception:  # broad catch: pynvml.NVMLError cannot be referenced if pynvml import fails
        return None


# ---------------------------------------------------------------------------
# PaddlePaddle fallback
# ---------------------------------------------------------------------------

def _query_gpu_memory_paddle() -> dict | None:
    """
    无 nvidia-smi 时，用 Paddle CUDA API 读显存（主进程若已 import paddle 且为 GPU 版）。
    used 为当前进程在 GPU 上已分配量；total 为卡总显存。单位 MiB。
    """
    try:
        import paddle

        if not paddle.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1:
            return None
        paddle.device.set_device("gpu:0")
        used = int(paddle.device.cuda.memory_allocated("gpu:0"))
        prop = paddle.device.cuda.get_device_properties(0)
        total = int(prop.total_memory)
        mib = 1024 * 1024
        return {"used_mb": used // mib, "total_mb": max(1, total // mib)}
    except Exception:  # broad catch: paddle internal errors are not part of public API
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_gpu_memory() -> dict | None:
    """查询 GPU 显存占用。Windows 优先 NVML，Linux 优先 nvidia-smi。"""
    # Windows：NVML 常比子进程更稳；Linux 上 nvidia-smi 更常见
    if os.name == "nt":
        order = (
            _query_gpu_memory_pynvml,
            _query_gpu_memory_nvidia_smi,
            _query_gpu_memory_paddle,
        )
    else:
        order = (
            _query_gpu_memory_nvidia_smi,
            _query_gpu_memory_pynvml,
            _query_gpu_memory_paddle,
        )
    for fn in order:
        m = fn()
        if m:
            return m
    return None
