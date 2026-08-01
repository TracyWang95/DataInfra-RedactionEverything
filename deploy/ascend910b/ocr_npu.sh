#!/bin/bash
# PP-StructureV3 OCR on Ascend NPU via official paddle-npu CANN 8.0 image.
# Do NOT mount host ascend-toolkit 8.3 — it breaks paddle-custom-npu static inference.
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
  -e OCR_VL_ENABLED=0 \
  -e OCR_STRUCTURE_ENABLED=1 \
  -e OCR_STRUCTURE_WARMUP=1 \
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
  "$IMAGE"

echo "OCR started: container=$NAME npu=$NPU_ID port=$PORT (Paddle NPU / CANN8.0 image)"
docker ps --filter "name=$NAME"
