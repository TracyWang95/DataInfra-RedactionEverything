#!/usr/bin/env bash
# 重启完整本地栈（mineru-document 预设）：
#   HaS Text vLLM → Locate LM vLLM → MinerU OCR → LocateAnything → 后端 → 前端
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

bash "${SCRIPT_DIR}/stop_all_local.sh"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "${PYTHON_BIN}" ]] && command -v conda >/dev/null 2>&1; then
  PYTHON_BIN="$(conda run --no-capture-output -n "${CONDA_ENV:-DataInfra_minerU}" which python)"
fi
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
export PYTHONPATH="${BACKEND_DIR}:${PYTHONPATH:-}"

BACKEND_PORT="${BACKEND_PORT:-8090}"
LOCATE_PORT="${LOCATE_ANYTHING_PORT:-8092}"
HAS_VLLM_PORT="${HAS_TEXT_VLLM_PORT:-8080}"
LOCATE_VLLM_PORT="${LOCATE_ANYTHING_VLLM_PORT:-8091}"
export OCR_PORT="${OCR_PORT:-9082}"
export OCR_BASE_URL="${OCR_BASE_URL:-http://127.0.0.1:${OCR_PORT}}"
export VISUAL_FEATURES_BASE_URL="${VISUAL_FEATURES_BASE_URL:-http://127.0.0.1:${LOCATE_PORT}}"
export MINERU_PIPELINE_BASE_URL="${MINERU_PIPELINE_BASE_URL:-${OCR_BASE_URL}}"

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

_wait_json_ready() {
  local url="$1" label="$2" max="${3:-300}"
  local i=1
  while [[ "${i}" -le "${max}" ]]; do
    if curl -sf "${url}" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ready') else 1)" 2>/dev/null; then
      echo "[restart] OK ${label}"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  echo "[restart] WARN ${label} 未 ready: ${url}" >&2
  return 1
}

# 1) HaS Text NER vLLM
if curl -sf "http://127.0.0.1:${HAS_VLLM_PORT}/v1/models" >/dev/null 2>&1; then
  echo "[restart] HaS Text vLLM 已在 ${HAS_VLLM_PORT} 运行，跳过启动"
else
  echo "[restart] 启动 HaS Text vLLM :${HAS_VLLM_PORT} ..."
  export HAS_TEXT_HF_MODEL="${HAS_TEXT_HF_MODEL_PATH:-${BACKEND_DIR}/models/has/HaS_Text_0209_0.6B}"
  export HAS_TEXT_VLLM_MAX_MODEL_LEN="${HAS_NER_CONTEXT_TOKENS:-16384}"
  nohup bash "${SCRIPT_DIR}/run_has_text_vllm.sh" >>"${LOG}/has_text_vllm.log" 2>&1 &
  echo $! >"${LOG}/has_text_vllm.pid"
  _wait_http "http://127.0.0.1:${HAS_VLLM_PORT}/v1/models" "HaS Text vLLM" 600 || true
fi

# 2) LocateAnything LM vLLM
if curl -sf "http://127.0.0.1:${LOCATE_VLLM_PORT}/v1/models" >/dev/null 2>&1; then
  echo "[restart] Locate LM vLLM 已在 ${LOCATE_VLLM_PORT} 运行，跳过启动"
else
  echo "[restart] 启动 Locate LM vLLM :${LOCATE_VLLM_PORT} ..."
  nohup bash "${SCRIPT_DIR}/run_locate_lm_vllm.sh" >>"${LOG}/locate_lm_vllm.log" 2>&1 &
  echo $! >"${LOG}/locate_vllm.pid"
  _wait_http "http://127.0.0.1:${LOCATE_VLLM_PORT}/v1/models" "Locate LM vLLM" 600 || true
fi

# 3) MinerU OCR
echo "[restart] 启动 MinerU OCR :${OCR_PORT} ..."
nohup env OCR_PORT="${OCR_PORT}" "${PYTHON_BIN}" "${BACKEND_DIR}/scripts/ocr_server.py" \
  >>"${LOG}/ocr_server.log" 2>&1 &
echo $! >"${LOG}/ocr_server.pid"
_wait_json_ready "http://127.0.0.1:${OCR_PORT}/health" "MinerU OCR" 600 || true

# 4) LocateAnything 视觉特征
LOCATE_MODEL="${LOCATE_ANYTHING_MODEL:-${BACKEND_DIR}/models/locateanything/LocateAnything-3B-HF}"
if [[ -d "${LOCATE_MODEL}" || -n "${LOCATE_ANYTHING_MODEL:-}" ]]; then
  echo "[restart] 启动 LocateAnything :${LOCATE_PORT} ..."
  nohup env LOCATE_ANYTHING_PORT="${LOCATE_PORT}" "${PYTHON_BIN}" \
    "${BACKEND_DIR}/scripts/locate_anything_server.py" \
    --model "${LOCATE_MODEL}" \
    --host 0.0.0.0 \
    --port "${LOCATE_PORT}" \
    >>"${LOG}/locate_anything.log" 2>&1 &
  echo $! >"${LOG}/locate_anything.pid"
  _wait_json_ready "http://127.0.0.1:${LOCATE_PORT}/health" "LocateAnything" 900 || true
else
  echo "[restart] 跳过 LocateAnything（未找到模型: ${LOCATE_MODEL}）" >&2
fi

# 5) 后端 API
echo "[restart] 启动后端 :${BACKEND_PORT} ..."
cd "${BACKEND_DIR}"
nohup env OCR_BASE_URL="${OCR_BASE_URL}" \
  MINERU_PIPELINE_BASE_URL="${MINERU_PIPELINE_BASE_URL}" \
  VISUAL_FEATURES_BASE_URL="${VISUAL_FEATURES_BASE_URL}" \
  OCR_STRUCTURE_ENABLED="${OCR_STRUCTURE_ENABLED:-false}" \
  "${PYTHON_BIN}" -m uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" \
  >>"${LOG}/backend.log" 2>&1 &
echo $! >"${LOG}/backend.pid"
_wait_http "http://127.0.0.1:${BACKEND_PORT}/health" "Backend" 60 || true

# 6) 应用 mineru-document 模型槽位预设
echo "[restart] 应用 mineru-document OCR 槽位预设 ..."
curl -sf -X POST "http://127.0.0.1:${BACKEND_PORT}/api/v1/model-config/presets/mineru-document/apply" >/dev/null 2>&1 || \
  echo "[restart] WARN: 无法自动应用 mineru-document 预设（可在设置页手动切换）" >&2

# 7) 前端 dev（后台）
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
bash "${SCRIPT_DIR}/start_frontend_background.sh"

echo ""
echo "======== 本地服务已后台启动（MinerU OCR 槽位）========"
echo "  前端:      http://127.0.0.1:${FRONTEND_PORT}/"
echo "  后端 API:  http://127.0.0.1:${BACKEND_PORT}"
echo "  MinerU:    ${OCR_BASE_URL}"
echo "  HaS NER:   http://127.0.0.1:${HAS_VLLM_PORT}/v1"
echo "  视觉特征:  ${VISUAL_FEATURES_BASE_URL}"
echo "  健康检查:  curl http://127.0.0.1:${BACKEND_PORT}/health/services"
echo "  停止:      ./scripts/stop_all_local.sh"
echo "  日志目录:  ${LOG}/"
echo "====================================================="
