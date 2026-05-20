#!/usr/bin/env bash
# 在 conda 环境 DataInfraNew 中启动 MinerU OCR 微服务
# 默认端口 9082（本机 8082 常被 MinIO 占用；与 backend/.env 中 OCR_BASE_URL 一致）
#
# 使用前请先安装依赖，例如：
#   conda activate DataInfraNew
#   pip install -r requirements-ocr.lock
#
# 指定端口：OCR_PORT=8082 ./scripts/run_ocr_server_conda.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"
cd "${ROOT}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/hf_mirror_env.sh"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

export OCR_PORT="${OCR_PORT:-9082}"
export OCR_BASE_URL="${OCR_BASE_URL:-http://127.0.0.1:${OCR_PORT}}"

if command -v ss >/dev/null 2>&1 && ss -tln | grep -q ":${OCR_PORT} "; then
  echo "[OCR] 端口 ${OCR_PORT} 已被占用。若已是本服务，可访问: ${OCR_BASE_URL}/health" >&2
  echo "[OCR] 换端口示例: OCR_PORT=9083 ./scripts/run_ocr_server_conda.sh" >&2
  exit 1
fi

echo "[OCR] 监听 0.0.0.0:${OCR_PORT} （HF 镜像 ${HF_ENDPOINT}，ModelScope ${MODELSCOPE_DOMAIN}）" >&2
exec conda run --no-capture-output -n DataInfraNew python scripts/ocr_server.py
