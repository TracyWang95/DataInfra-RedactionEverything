#!/bin/bash
# PP-StructureV3 on Ascend NPU + PaddleOCR-VL client (vl_rec_backend=vllm-server).
# VL weights run on official genai-vllm-server (see vl_genai_npu.sh), NOT local paddle-npu.
# Docs: https://www.paddleocr.ai/main/version3.x/pipeline_usage/PaddleOCR-VL-Huawei-Ascend-NPU.html
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

NPU_ID="${OCR_NPU_ID:-2}"
PORT="${OCR_PORT:-8082}"
NAME="${OCR_CONTAINER_NAME:-redaction-ocr-npu}"
IMAGE="${OCR_IMAGE:-redaction-ocr-npu:latest}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build -t "$IMAGE" -f "$REPO_ROOT/backend/Dockerfile.ocr.npu" "$REPO_ROOT/backend"
fi

CACHE_ROOT="${OCR_CACHE_ROOT:-/data/ljc/caches/ocr}"
mkdir -p "$CACHE_ROOT/paddlex" "$CACHE_ROOT/paddle" "$CACHE_ROOT/huggingface" "$CACHE_ROOT/modelscope"
chmod -R a+rwX "$CACHE_ROOT" || true

docker rm -f redaction-ocr-cpu "$NAME" 2>/dev/null || true

# Driver-only mounts (image provides CANN 8.0 + nnal).
# shellcheck disable=SC2046
docker run -d --name "$NAME" --restart unless-stopped \
  --shm-size=8g \
  --network host \
  $(npu_docker_common_flags) \
  $(npu_docker_devices "$NPU_ID") \
  -v /usr/local/dcmi:/usr/local/dcmi:ro \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi:ro \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver:ro \
  -e ASCEND_RT_VISIBLE_DEVICES="$NPU_ID" \
  -e OCR_PORT="$PORT" \
  -e OCR_VL_ENABLED="${OCR_VL_ENABLED:-1}" \
  -e OCR_STRUCTURE_ENABLED=1 \
  -e OCR_STRUCTURE_WARMUP=1 \
  -e OCR_VL_BACKEND="${OCR_VL_BACKEND:-vllm-server}" \
  -e OCR_VLLM_URL="${OCR_VLLM_URL:-http://127.0.0.1:8118/v1}" \
  -e OCR_VL_API_MODEL_NAME="${OCR_VL_API_MODEL_NAME:-PaddleOCR-VL-1.6-0.9B}" \
  -e OCR_VL_MAX_CONCURRENCY="${OCR_VL_MAX_CONCURRENCY:-64}" \
  -e OCR_ALLOW_CPU=0 \
  -e OCR_DEVICE=npu \
  -e OCR_PIPELINE_DEVICE=npu:0 \
  -e FLAGS_npu_jit_compile=false \
  -e FLAGS_npu_scale_aclnn=True \
  -e FLAGS_npu_split_aclnn=True \
  -e FLAGS_use_stride_kernel=0 \
  -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  -e PADDLE_PDX_MODEL_SOURCE=modelscope \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e HOME=/home/appuser \
  -e PYTHONUNBUFFERED=1 \
  -v "$CACHE_ROOT/paddlex:/home/appuser/.paddlex" \
  -v "$CACHE_ROOT/paddle:/home/appuser/.cache/paddle" \
  -v "$CACHE_ROOT/huggingface:/home/appuser/.cache/huggingface" \
  -v "$CACHE_ROOT/modelscope:/home/appuser/.cache/modelscope" \
  -v "$REPO_ROOT/backend/scripts/ocr_server.py:/app/ocr_server.py:ro" \
  "$IMAGE"

echo "OCR started: container=$NAME npu=$NPU_ID port=$PORT (Structure NPU + VL via genai :8118)"
docker ps --filter "name=$NAME"
