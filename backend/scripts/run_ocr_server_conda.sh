#!/usr/bin/env bash
# 在 conda 环境 DataInfra 中启动 MinerU OCR 微服务（默认端口 8082）
# 使用前请先安装依赖，例如：
#   conda activate DataInfra
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
#   pip install -r requirements-ocr.lock
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
cd "${ROOT}"
exec conda run --no-capture-output -n DataInfra python scripts/ocr_server.py
