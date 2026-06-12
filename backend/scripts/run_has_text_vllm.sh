#!/usr/bin/env bash
# 启动 HaS Text 用的 vLLM（OpenAI 兼容 @8000）。
# 默认 gpu-memory-utilization=0.70，为同卡 MinerU OCR / GLM VLM 留出显存。
#
# 用法（backend 目录）：
#   ./scripts/run_has_text_vllm.sh
# 覆盖显存比例：
#   VLLM_GPU_MEMORY_UTILIZATION=0.65 ./scripts/run_has_text_vllm.sh
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

VLLM_PORT="${HAS_TEXT_VLLM_PORT:-8000}"
VLLM_ENV="${VLLM_CONDA_ENV:-vllm312}"
MODEL="${HAS_TEXT_HF_MODEL:-unsloth/Qwen3.6-35B-A3B-NVFP4}"
UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.70}"
MAX_LEN="${HAS_TEXT_VLLM_MAX_MODEL_LEN:-40960}"
EXTRA="${HAS_TEXT_VLLM_EXTRA_ARGS:-}"

VLLM_BIN="${VLLM_BIN:-}"
if [[ -z "${VLLM_BIN}" ]]; then
  if command -v conda >/dev/null 2>&1; then
    VLLM_BIN="$(conda run --no-capture-output -n "${VLLM_ENV}" which vllm 2>/dev/null || true)"
  fi
  VLLM_BIN="${VLLM_BIN:-$(command -v vllm || true)}"
fi
if [[ -z "${VLLM_BIN}" || ! -x "${VLLM_BIN}" ]]; then
  echo "[vLLM] FATAL: 找不到 vllm，请设置 VLLM_BIN 或 conda 环境 ${VLLM_ENV}" >&2
  exit 1
fi

if ss -tln 2>/dev/null | grep -q ":${VLLM_PORT} "; then
  echo "[vLLM] 端口 ${VLLM_PORT} 已被占用。若需按 0.70 显存重启，请先: ./scripts/stop_has_text_vllm.sh" >&2
  exit 1
fi

echo "[vLLM] 启动 ${MODEL} @:${VLLM_PORT} gpu-memory-utilization=${UTIL} max-model-len=${MAX_LEN}" >&2
echo "[vLLM] 日志: ${LOG}/vllm.log" >&2

# shellcheck disable=SC2086
SERVED_NAME="${HAS_TEXT_MODEL_NAME:-HaS_Text_0209_0.6B}"

exec "${VLLM_BIN}" serve "${MODEL}" \
  --host 0.0.0.0 \
  --port "${VLLM_PORT}" \
  --served-model-name "${SERVED_NAME}" \
  --trust-remote-code \
  --dtype bfloat16 \
  --max-model-len "${MAX_LEN}" \
  --gpu-memory-utilization "${UTIL}" \
  ${EXTRA}
