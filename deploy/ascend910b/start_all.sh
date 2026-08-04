#!/bin/bash
# Start Ascend model sidecars + wire docker compose backend/frontend.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

cd "$REPO_ROOT"

echo "=== [1/6] ensure models ==="
if [[ ! -f backend/models/has/HaS_Text_0209_0.6B/config.json ]] \
  || [[ ! -f backend/models/locateanything/LocateAnything-3B-HF/config.json ]]; then
  python3 -m pip install -q -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" \
    modelscope 'huggingface_hub>=0.25'
  python3 backend/scripts/download_models.py
fi

echo "=== [2/6] start PaddleOCR-VL genai (official NPU image, :8118) ==="
bash "$SCRIPT_DIR/vl_genai_npu.sh"

echo "=== [3/6] start OCR Structure + VL client (NPU2) ==="
bash "$SCRIPT_DIR/ocr_npu.sh"

echo "=== [4/6] start HaS (vllm-ascend NPU0) ==="
bash "$SCRIPT_DIR/has_npu.sh"

echo "=== [5/6] start LocateAnything (NPU1) ==="
bash "$SCRIPT_DIR/la_npu.sh"

if [[ -f "$SCRIPT_DIR/yolo_npu.sh" ]]; then
  echo "=== [6/6] start YOLO HaS-Image (NPU3) ==="
  bash "$SCRIPT_DIR/yolo_npu.sh"
else
  echo "=== [6/6] skip YOLO (yolo_npu.sh missing) ==="
fi

echo "=== compose up backend/frontend with ascend overlay ==="
docker compose -f docker-compose.yml -f docker-compose.ascend.yml up -d backend frontend

echo "DONE."
echo "  Docs:  $SCRIPT_DIR/README.md"
echo "  Check: curl -s http://127.0.0.1:8000/health/services | python3 -m json.tool"
