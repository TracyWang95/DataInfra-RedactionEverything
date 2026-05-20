#!/usr/bin/env bash
# 启动 GLM VLM（llama.cpp server），供视觉语义 / 签字等清单识别使用。
# 默认端口 8091（后端 API 在 8090，勿混用）。
# 默认使用国内 HF 镜像 https://hf-mirror.com（见 scripts/hf_mirror_env.sh）。
#
# 与 vLLM(HaS Text @8000) 同卡时，vLLM 常占满显存导致本服务 CUDA OOM。
#   - 推荐：调低 vLLM --gpu-memory-utilization（如 0.70），为 VLM 留出 ≥12GB
#   - 或：GLM_FLASH_FORCE_CPU=1 ./scripts/run_vlm_llama_server.sh（慢，但能起）
#
# 用法（backend 目录）：
#   ./scripts/run_vlm_llama_server.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/hf_mirror_env.sh"

if [[ -f "${BACKEND_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${BACKEND_DIR}/.env"
  set +a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/hf_mirror_env.sh"
fi

LLAMA_SERVER="${GLM_FLASH_SERVER_BIN:-/home/evalops/Desktop/work/llama.cpp/build/bin/llama-server}"
VLM_PORT="${GLM_FLASH_PORT:-8091}"
VLM_MODELS_DIR="${VLM_MODELS_DIR:-${BACKEND_DIR}/models/vlm}"
MODEL="${GLM_FLASH_MODEL_FOR_SERVER:-}"
MMPROJ="${GLM_FLASH_MMPROJ_FOR_SERVER:-}"
if [[ -z "${MODEL}" && -f "${VLM_MODELS_DIR}/GLM-4.6V-Flash-Q4_K_M.gguf" ]]; then
  MODEL="${VLM_MODELS_DIR}/GLM-4.6V-Flash-Q4_K_M.gguf"
fi
if [[ -z "${MMPROJ}" && -f "${VLM_MODELS_DIR}/mmproj-GLM-4.6V-Flash-Q8_0.gguf" ]]; then
  MMPROJ="${VLM_MODELS_DIR}/mmproj-GLM-4.6V-Flash-Q8_0.gguf"
fi
ALIAS="${GLM_FLASH_ALIAS:-${VLM_MODEL_NAME:-GLM-4.6V-Flash-Q4_K_M}}"
MIN_FREE_MIB="${GLM_FLASH_MIN_FREE_VRAM_MIB:-12288}"

_gpu_free_mib() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo ""
    return 0
  fi
  local used total
  used="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
  total="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
  if [[ -z "${used}" || -z "${total}" || "${total}" == "[N/A]" ]]; then
    echo ""
    return 0
  fi
  echo $((total - used))
}

if [[ ! -x "${LLAMA_SERVER}" ]]; then
  echo "[VLM] FATAL: 找不到 llama-server: ${LLAMA_SERVER}" >&2
  echo "[VLM] 请编译 llama.cpp 或设置 GLM_FLASH_SERVER_BIN" >&2
  exit 1
fi

if ss -tln 2>/dev/null | grep -q ":${VLM_PORT} "; then
  echo "[VLM] 端口 ${VLM_PORT} 已占用。探活: curl -sS http://127.0.0.1:${VLM_PORT}/v1/models" >&2
  exit 1
fi

FREE_MIB="$(_gpu_free_mib)"
FORCE_CPU="${GLM_FLASH_FORCE_CPU:-}"
if [[ "${FORCE_CPU}" == "1" || "${FORCE_CPU,,}" == "true" || "${FORCE_CPU,,}" == "yes" ]]; then
  echo "[VLM] GLM_FLASH_FORCE_CPU=1：禁用 CUDA，纯 CPU 推理（较慢）" >&2
  export CUDA_VISIBLE_DEVICES=""
  NGL="${GLM_FLASH_N_GPU_LAYERS:-0}"
elif [[ -n "${FREE_MIB}" && "${FREE_MIB}" -lt "${MIN_FREE_MIB}" ]]; then
  echo "[VLM] WARN: GPU 空闲显存约 ${FREE_MIB} MiB < ${MIN_FREE_MIB} MiB（vLLM/MinerU 可能已占满）" >&2
  echo "[VLM] 可选方案：" >&2
  echo "[VLM]   1) 降低 vLLM 显存占用后重试，例如 --gpu-memory-utilization 0.70" >&2
  echo "[VLM]   2) 强制 CPU: GLM_FLASH_FORCE_CPU=1 $0" >&2
  echo "[VLM]   3) 暂时停止 vLLM，仅跑 VLM" >&2
  if [[ "${GLM_FLASH_AUTO_CPU_ON_OOM:-1}" != "0" ]]; then
    echo "[VLM] 已自动切换为 CPU 模式（设 GLM_FLASH_AUTO_CPU_ON_OOM=0 可改为直接退出）" >&2
    export CUDA_VISIBLE_DEVICES=""
    NGL="${GLM_FLASH_N_GPU_LAYERS:-0}"
  else
    exit 1
  fi
else
  NGL="${GLM_FLASH_N_GPU_LAYERS:-auto}"
  if [[ -n "${FREE_MIB}" ]]; then
    echo "[VLM] GPU 空闲显存约 ${FREE_MIB} MiB，使用 -ngl ${NGL} -fit on" >&2
  fi
fi

ARGS=(
  --host 0.0.0.0
  --port "${VLM_PORT}"
  -ngl "${NGL}"
  -fit "${GLM_FLASH_FIT:-on}"
  -fa "${GLM_FLASH_FLASH_ATTN:-on}"
  -c "${GLM_FLASH_N_CTX:-2048}"
  -np "${GLM_FLASH_N_PARALLEL:-1}"
  --alias "${ALIAS}"
  --temp "${GLM_FLASH_TEMP:-0.8}"
  --top-p "${GLM_FLASH_TOP_P:-0.6}"
)

if [[ -n "${MODEL}" && -f "${MODEL}" ]]; then
  ARGS+=(-m "${MODEL}")
  if [[ -n "${MMPROJ}" && -f "${MMPROJ}" ]]; then
    ARGS+=(--mmproj "${MMPROJ}")
  fi
else
  echo "[VLM] FATAL: 未找到本地 GGUF。llama-server 未启用 HTTPS，无法直连 HF。" >&2
  echo "[VLM] 请先执行: ./scripts/download_vlm_gguf.sh" >&2
  echo "[VLM] 或设置 GLM_FLASH_MODEL_FOR_SERVER / GLM_FLASH_MMPROJ_FOR_SERVER" >&2
  exit 1
fi

if [[ "${GLM_FLASH_MMPROJ_OFFLOAD:-1}" != "0" && -z "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  ARGS+=(--mmproj-offload)
fi

echo "[VLM] ${LLAMA_SERVER} 监听 :${VLM_PORT} alias=${ALIAS} mirror=${HF_ENDPOINT} ngl=${NGL}" >&2
exec "${LLAMA_SERVER}" "${ARGS[@]}"
