#!/usr/bin/env bash
# 停止本项目的本地进程（backend / OCR / LocateAnything / 前端 dev 等）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ROOT}/logs"

for name in backend ocr_server locate_anything locate_vllm has_text_vllm vlm vllm has_text frontend; do
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
pkill -f "${ROOT}/scripts/locate_anything_server.py" 2>/dev/null || true
pkill -f "uvicorn app.main:app.*--port" 2>/dev/null || true
pkill -f "llama-server.*--port 8091" 2>/dev/null || true
pkill -f "llama-server.*--port 8088" 2>/dev/null || true
pkill -f "${ROOT}/scripts/run_has_text_vllm.sh" 2>/dev/null || true
pkill -f "${ROOT}/scripts/run_locate_lm_vllm.sh" 2>/dev/null || true
pkill -f "vllm serve.*${ROOT}/models/has/" 2>/dev/null || true
pkill -f "vllm serve.*locate_qwen2_model" 2>/dev/null || true
pkill -f "${ROOT}/../frontend/node_modules/.bin/vite" 2>/dev/null || true
pkill -f "vite --host" 2>/dev/null || true

for port in 8090 9082 8092 8091 8080 8088 3000 8000; do
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  fi
done

sleep 2
echo "[stop] 完成"
