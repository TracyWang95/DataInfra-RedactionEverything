#!/usr/bin/env bash
# 后台启动：主后端 API（8000）+ MinerU OCR（8082）+ HaS Image（8081）
#
# HaS Image（has_image_server）：Ultralytics YOLO11 实例分割微服务，用于图像中多类隐私区域检测；
# 与主后端分离进程，主后端通过 HAS_IMAGE_BASE_URL（默认 http://127.0.0.1:8081）调用。
#
# 依赖：
#   - conda 环境 DataInfra；OCR 另需 requirements-ocr.lock；HaS Image 需权重与 requirements-vision.lock
#   - 主后端须已安装 backend/requirements.txt，否则 uvicorn 会因缺包退出（见 logs/backend.log）
# 用法（在 backend 目录下）:
#   ./scripts/start_backend_and_vision_background.sh
# 日志与 PID：backend/logs/
# 停止示例：
#   kill $(cat logs/backend.pid) $(cat logs/ocr_server.pid) $(cat logs/has_image_server.pid)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ROOT}/logs"
mkdir -p "${LOG}"
cd "${ROOT}"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"

CONDA_ENV="${CONDA_ENV:-DataInfra}"
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="${PYTHON}"
elif command -v conda &>/dev/null; then
  PYTHON_BIN="$(conda run --no-capture-output -n "${CONDA_ENV}" which python)"
else
  PYTHON_BIN="$(command -v python3)"
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[start] FATAL: 无法解析可执行的 Python: ${PYTHON_BIN}" >&2
  exit 1
fi
echo "[start] 使用 Python: ${PYTHON_BIN}"

echo "[start] backend -> ${LOG}/backend.log (port 8000)"
nohup "${PYTHON_BIN}" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >>"${LOG}/backend.log" 2>&1 &
echo $! >"${LOG}/backend.pid"

echo "[start] ocr_server -> ${LOG}/ocr_server.log (port 8082)"
nohup "${PYTHON_BIN}" scripts/ocr_server.py >>"${LOG}/ocr_server.log" 2>&1 &
echo $! >"${LOG}/ocr_server.pid"

echo "[start] has_image_server -> ${LOG}/has_image_server.log (port 8081)"
nohup "${PYTHON_BIN}" scripts/has_image_server.py >>"${LOG}/has_image_server.log" 2>&1 &
echo $! >"${LOG}/has_image_server.pid"

sleep 1
echo "[start] 已写入 PID: ${LOG}/backend.pid ${LOG}/ocr_server.pid ${LOG}/has_image_server.pid"
echo "[start] 探活: curl -sS http://127.0.0.1:8000/health | head -c 200; echo"
echo "[start]       curl -sS http://127.0.0.1:8082/health; echo"
echo "[start]       curl -sS http://127.0.0.1:8081/health; echo"
