#!/usr/bin/env bash
# LocateAnything LM backbone via vLLM (prompt-embeds) @8091
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG="${BACKEND_DIR}/logs"
mkdir -p "${LOG}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/hf_mirror_env.sh"

if [[ -f "${BACKEND_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${BACKEND_DIR}/.env"
  set +a
fi

VLLM_PORT="${LOCATE_ANYTHING_VLLM_PORT:-8091}"
VLLM_ENV="${VLLM_CONDA_ENV:-vllm312}"
MODEL="${LOCATE_ANYTHING_LM_MODEL_DIR:-${BACKEND_DIR}/models/locateanything/locate_qwen2_model}"
SERVED="${LOCATE_ANYTHING_VLLM_MODEL:-locate_qwen2_model}"
UTIL="${LOCATE_LM_GPU_MEMORY_UTILIZATION:-0.25}"
MAX_LEN="${LOCATE_LM_MAX_MODEL_LEN:-8192}"

VLLM_BIN="${VLLM_BIN:-}"
if [[ -z "${VLLM_BIN}" ]] && command -v conda >/dev/null 2>&1; then
  VLLM_BIN="$(conda run --no-capture-output -n "${VLLM_ENV}" which vllm 2>/dev/null || true)"
fi
VLLM_BIN="${VLLM_BIN:-$(command -v vllm || true)}"
if [[ -z "${VLLM_BIN}" || ! -x "${VLLM_BIN}" ]]; then
  echo "[locate-vLLM] FATAL: 找不到 vllm，请设置 VLLM_BIN 或 conda 环境 ${VLLM_ENV}" >&2
  exit 1
fi

if ss -tln 2>/dev/null | grep -q ":${VLLM_PORT} "; then
  echo "[locate-vLLM] 端口 ${VLLM_PORT} 已被占用" >&2
  exit 1
fi

echo "[locate-vLLM] 启动 ${MODEL} @:${VLLM_PORT} gpu-memory-utilization=${UTIL}" >&2
exec env CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" \
  HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" \
  PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}" \
  "${VLLM_BIN}" serve "${MODEL}" \
  --served-model-name "${SERVED}" \
  --host 0.0.0.0 \
  --port "${VLLM_PORT}" \
  --enable-prompt-embeds \
  --dtype bfloat16 \
  --gpu-memory-utilization "${UTIL}" \
  --max-model-len "${MAX_LEN}" \
  --enforce-eager
