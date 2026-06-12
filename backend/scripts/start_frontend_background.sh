#!/usr/bin/env bash
# 后台启动 Vite 前端 dev（默认 :3000）
#
# 用法（backend 目录）:
#   ./scripts/start_frontend_background.sh
# 日志与 PID：backend/logs/frontend.log、frontend.pid
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${BACKEND_DIR}/.." && pwd)"
FRONTEND_DIR="${REPO_DIR}/frontend"
LOG="${BACKEND_DIR}/logs"
mkdir -p "${LOG}"

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8090}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"

VITE_BIN="${FRONTEND_DIR}/node_modules/.bin/vite"
if [[ ! -x "${VITE_BIN}" ]]; then
  echo "[frontend] FATAL: 未找到 ${VITE_BIN}，请先: cd ${FRONTEND_DIR} && npm ci" >&2
  exit 1
fi

if curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
  echo "[frontend] 端口 ${FRONTEND_PORT} 已有 HTTP 服务，跳过启动"
  exit 0
fi

export BACKEND_URL
export VITE_BACKEND_URL="${VITE_BACKEND_URL:-${BACKEND_URL}}"

echo "[frontend] 后台启动 Vite :${FRONTEND_PORT} -> ${LOG}/frontend.log"
cd "${FRONTEND_DIR}"
nohup "${VITE_BIN}" --host 0.0.0.0 --port "${FRONTEND_PORT}" >>"${LOG}/frontend.log" 2>&1 &
echo $! >"${LOG}/frontend.pid"

_wait_http() {
  local i=1
  while [[ "${i}" -le 30 ]]; do
    if curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
      echo "[frontend] OK http://127.0.0.1:${FRONTEND_PORT}/"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "[frontend] WARN: 未在 30s 内就绪，请查看 ${LOG}/frontend.log" >&2
  return 1
}

_wait_http || true
