#!/bin/bash
# Official PaddleOCR-VL VLM server on Ascend NPU (genai + vLLM).
# Docs: https://www.paddleocr.ai/main/version3.x/pipeline_usage/PaddleOCR-VL-Huawei-Ascend-NPU.html
# Local PaddleOCRVL(device=npu) direct inference is NOT supported; this service is.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

NPU_ID="${VL_NPU_ID:-4}"
PORT="${OCR_VL_PORT:-8118}"
NAME="${VL_CONTAINER_NAME:-redaction-vl-genai-npu}"
IMAGE="${OCR_VL_GENAI_IMAGE:-ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-huawei-npu}"
MODEL_NAME="${OCR_VL_API_MODEL_NAME:-PaddleOCR-VL-1.6-0.9B}"

echo "Pulling $IMAGE (official Ascend VL genai server) ..."
docker pull "$IMAGE"

# Stop previous VL attempts (CPU fallback / broken generic vllm-ascend).
docker rm -f redaction-ocr-vl-cpu redaction-vl-npu "$NAME" 2>/dev/null || true

# shellcheck disable=SC2046
docker run -d --name "$NAME" --restart unless-stopped \
  --user root \
  --privileged \
  --shm-size=64g \
  --network host \
  $(npu_docker_devices "$NPU_ID") \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver:ro \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi:ro \
  -v /usr/local/dcmi:/usr/local/dcmi:ro \
  -e ASCEND_RT_VISIBLE_DEVICES="$NPU_ID" \
  -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  -e PYTHONUNBUFFERED=1 \
  "$IMAGE" \
  paddleocr genai_server \
    --model_name "$MODEL_NAME" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --backend vllm

echo "VL genai started: container=$NAME npu=$NPU_ID port=$PORT image=$IMAGE"
docker ps --filter "name=$NAME"
