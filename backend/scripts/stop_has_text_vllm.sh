#!/usr/bin/env bash
# 停止本机 HaS Text vLLM（默认端口 8000）
set -euo pipefail
PORT="${HAS_TEXT_VLLM_PORT:-8000}"
echo "[vLLM] 停止端口 ${PORT} 上的 vLLM ..."
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
fi
pkill -f "vllm serve.*--port ${PORT}" 2>/dev/null || pkill -f "vllm serve" 2>/dev/null || true
sleep 2
if ss -tln 2>/dev/null | grep -q ":${PORT} "; then
  echo "[vLLM] WARN: 端口 ${PORT} 仍被占用，请手动检查: ss -tlnp | grep ${PORT}" >&2
  exit 1
fi
echo "[vLLM] 已停止"
