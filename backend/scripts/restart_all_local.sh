#!/usr/bin/env bash
# 重启完整本地栈：vLLM(0.70) → MinerU OCR → HaS Image → GLM VLM → 后端 → 提示启动前端
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${BACKEND_DIR}/.." && pwd)"
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

bash "${SCRIPT_DIR}/stop_all_local.sh"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "${PYTHON_BIN}" ]] && command -v conda >/dev/null 2>&1; then
  PYTHON_BIN="$(conda run --no-capture-output -n "${CONDA_ENV:-DataInfraNew}" which python)"
fi
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
export PYTHONPATH="${BACKEND_DIR}:${PYTHONPATH:-}"

_wait_http() {
  local url="$1" label="$2" max="${3:-120}"
  local i=1
  while [[ "${i}" -le "${max}" ]]; do
    if curl -sf "${url}" >/dev/null 2>&1; then
      echo "[restart] OK ${label}"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  echo "[restart] WARN ${label} 未在时间内就绪: ${url}" >&2
  return 1
}

# 1) HaS Text NER @8088（勿与 8000 的 Qwen vLLM 混用）
if curl -sf http://127.0.0.1:8088/v1/models >/dev/null 2>&1; then
  echo "[restart] HaS Text 已在 8088 运行，跳过启动"
else
  echo "[restart] 启动 HaS Text llama-server ..."
  nohup bash "${SCRIPT_DIR}/run_has_text_llama_server.sh" >>"${LOG}/has_text.log" 2>&1 &
  echo $! >"${LOG}/has_text.pid"
  _wait_http "http://127.0.0.1:8088/v1/models" "HaS Text" 60 || true
fi

# 2) vLLM @8000（可选，默认不启动；与 HaS NER 无关，占大量显存）
if [[ "${START_OPTIONAL_VLLM:-0}" == "1" ]]; then
  if curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
    echo "[restart] vLLM 已在 8000 运行，跳过启动"
  else
    echo "[restart] 启动 vLLM (gpu-memory-utilization=0.70) ..."
    nohup bash "${SCRIPT_DIR}/run_has_text_vllm.sh" >>"${LOG}/vllm.log" 2>&1 &
    echo $! >"${LOG}/vllm.pid"
    _wait_http "http://127.0.0.1:8000/v1/models" "vLLM" 600 || true
  fi
else
  echo "[restart] 跳过可选 vLLM @8000（设 START_OPTIONAL_VLLM=1 可启用）"
fi

# 3) MinerU OCR
echo "[restart] 启动 MinerU OCR ..."
export OCR_PORT="${OCR_PORT:-9082}"
nohup env OCR_PORT="${OCR_PORT}" "${PYTHON_BIN}" "${BACKEND_DIR}/scripts/ocr_server.py" \
  >>"${LOG}/ocr_server.log" 2>&1 &
echo $! >"${LOG}/ocr_server.pid"
_wait_http "http://127.0.0.1:${OCR_PORT}/health" "MinerU OCR" 300 || true

# 4) HaS Image
echo "[restart] 启动 HaS Image ..."
nohup "${PYTHON_BIN}" "${BACKEND_DIR}/scripts/has_image_server.py" \
  >>"${LOG}/has_image_server.log" 2>&1 &
echo $! >"${LOG}/has_image_server.pid"
_wait_http "http://127.0.0.1:8081/health" "HaS Image" 120 || true

# 5) GLM VLM（本地 GGUF）
VLM_DIR="${VLM_MODELS_DIR:-${BACKEND_DIR}/models/vlm}"
if [[ -f "${VLM_DIR}/GLM-4.6V-Flash-Q4_K_M.gguf" ]]; then
  echo "[restart] 启动 GLM VLM ..."
  export GLM_FLASH_MODEL_FOR_SERVER="${GLM_FLASH_MODEL_FOR_SERVER:-${VLM_DIR}/GLM-4.6V-Flash-Q4_K_M.gguf}"
  export GLM_FLASH_MMPROJ_FOR_SERVER="${GLM_FLASH_MMPROJ_FOR_SERVER:-${VLM_DIR}/mmproj-GLM-4.6V-Flash-Q8_0.gguf}"
  export GLM_FLASH_AUTO_CPU_ON_OOM=0
  nohup bash "${SCRIPT_DIR}/run_vlm_llama_server.sh" >>"${LOG}/vlm.log" 2>&1 &
  echo $! >"${LOG}/vlm.pid"
  _wait_http "http://127.0.0.1:8091/v1/models" "GLM VLM" 180 || true
else
  echo "[restart] 跳过 VLM（未找到 ${VLM_DIR}/GLM-4.6V-Flash-Q4_K_M.gguf）" >&2
fi

# 6) 后端 API
BACKEND_PORT="${BACKEND_PORT:-8090}"
echo "[restart] 启动后端 :${BACKEND_PORT} ..."
cd "${BACKEND_DIR}"
nohup "${PYTHON_BIN}" -m uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" \
  >>"${LOG}/backend.log" 2>&1 &
echo $! >"${LOG}/backend.pid"
_wait_http "http://127.0.0.1:${BACKEND_PORT}/health" "Backend" 30

# 7) 前端 dev（后台）
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
bash "${SCRIPT_DIR}/start_frontend_background.sh"

echo ""
echo "======== 本地服务已后台启动 ========"
echo "  前端:      http://127.0.0.1:${FRONTEND_PORT}/"
echo "  后端 API:  http://127.0.0.1:${BACKEND_PORT}"
echo "  健康检查:  curl http://127.0.0.1:${BACKEND_PORT}/health/services"
echo "  停止:      ./scripts/stop_all_local.sh"
echo "  日志目录:  ${LOG}/"
echo "===================================="
