#!/usr/bin/env bash
# 停止本项目的本地进程（backend / OCR / HaS Image / VLM / 前端 dev）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ROOT}/logs"

for name in backend ocr_server has_image_server vlm vllm has_text frontend; do
  pidfile="${LOG}/${name}.pid"
  if [[ -f "${pidfile}" ]]; then
    pid="$(cat "${pidfile}")"
    if kill -0 "${pid}" 2>/dev/null; then
      echo "[stop] ${name} pid=${pid}"
      kill "${pid}" 2>/dev/null || true
    fi
    rm -f "${pidfile}"
  fi
done

pkill -f "${ROOT}/scripts/ocr_server.py" 2>/dev/null || true
pkill -f "${ROOT}/scripts/has_image_server.py" 2>/dev/null || true
pkill -f "uvicorn app.main:app.*--port" 2>/dev/null || true
pkill -f "llama-server.*--port 8091" 2>/dev/null || true
pkill -f "llama-server.*--port 8088" 2>/dev/null || true
pkill -f "${ROOT}/../frontend/node_modules/.bin/vite" 2>/dev/null || true
pkill -f "vite --host" 2>/dev/null || true

for port in 8090 9082 8081 8091 8088 3000; do
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  fi
done

sleep 2
echo "[stop] 完成"
