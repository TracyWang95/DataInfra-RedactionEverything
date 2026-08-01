#!/bin/bash
# Start Ascend model sidecars + wire docker compose backend/frontend.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

cd "$REPO_ROOT"

echo "=== [1/4] ensure models ==="
if [[ ! -f backend/models/has/HaS_Text_0209_0.6B/config.json ]] \
  || [[ ! -f backend/models/locateanything/LocateAnything-3B-HF/config.json ]]; then
  python3 -m pip install -q -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" \
    modelscope 'huggingface_hub>=0.25'
  python3 backend/scripts/download_models.py
fi

echo "=== [2/4] start OCR (NPU Structure) ==="
bash "$SCRIPT_DIR/ocr_npu.sh"

echo "=== [3/4] start HaS (vllm-ascend NPU0) ==="
bash "$SCRIPT_DIR/has_npu.sh"

echo "=== [4/4] start LocateAnything (NPU1) ==="
bash "$SCRIPT_DIR/la_npu.sh"

echo "=== compose up backend/frontend with ascend overlay ==="
docker compose -f docker-compose.yml -f docker-compose.ascend.yml up -d backend frontend

echo "DONE. Check: curl -s http://127.0.0.1:8000/health/services | python3 -m json.tool"
