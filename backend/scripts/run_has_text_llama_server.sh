#!/usr/bin/env bash
# 启动 HaS Text NER（llama-server，OpenAI 兼容），与通用 vLLM(Qwen) 分离。
# 默认端口 8088，模型默认使用 llama.cpp/models/has/HaS_Text_0209_0.6B_Q4_K_M.gguf
#
# 用法（backend 目录）：
#   ./scripts/run_has_text_llama_server.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/hf_mirror_env.sh"

LLAMA_SERVER="${HAS_TEXT_LLAMA_BIN:-/home/evalops/Desktop/work/llama.cpp/build/bin/llama-server}"
PORT="${HAS_TEXT_LLAMA_PORT:-8088}"
MODEL="${HAS_TEXT_GGUF:-/home/evalops/Desktop/work/llama.cpp/models/has/HaS_Text_0209_0.6B_Q4_K_M.gguf}"
ALIAS="${HAS_TEXT_MODEL_NAME:-HaS_Text_0209}"

if [[ ! -x "${LLAMA_SERVER}" ]]; then
  echo "[HaS-Text] FATAL: 找不到 llama-server: ${LLAMA_SERVER}" >&2
  exit 1
fi
if [[ ! -f "${MODEL}" ]]; then
  echo "[HaS-Text] FATAL: 找不到 GGUF: ${MODEL}" >&2
  echo "[HaS-Text] 请下载 HaS_Text_0209_0.6B_Q4_K_M.gguf 到 models/has/" >&2
  exit 1
fi

if ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  echo "[HaS-Text] 端口 ${PORT} 已占用。探活: curl -sS http://127.0.0.1:${PORT}/v1/models" >&2
  exit 1
fi

echo "[HaS-Text] ${MODEL}" >&2
echo "[HaS-Text] 监听 :${PORT} alias=${ALIAS}" >&2
exec "${LLAMA_SERVER}" \
  -m "${MODEL}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  -ngl "${HAS_TEXT_N_GPU_LAYERS:-99}" \
  -c "${HAS_TEXT_N_CTX:-8192}" \
  -np 4 \
  -a "${ALIAS}" \
  --temp 0 \
  --top-p 0.6
