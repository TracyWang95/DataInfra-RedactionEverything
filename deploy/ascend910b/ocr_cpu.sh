#!/bin/bash
# PP-StructureV3 OCR on CPU paddle (Ascend interim until Paddle-NPU is wired)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

PORT="${OCR_PORT:-8082}"
NAME="${OCR_CONTAINER_NAME:-redaction-ocr-cpu}"
IMAGE="${OCR_IMAGE:-redaction-ocr-cpu:latest}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build -t "$IMAGE" -f "$REPO_ROOT/backend/Dockerfile.ocr.cpu" "$REPO_ROOT/backend"
fi

CACHE_ROOT="${OCR_CACHE_ROOT:-/data/ljc/caches/ocr}"
mkdir -p "$CACHE_ROOT/paddlex" "$CACHE_ROOT/paddle" "$CACHE_ROOT/huggingface" "$CACHE_ROOT/modelscope"
# container runs as appuser (uid 1000 typically); keep host cache writable
chmod -R a+rwX "$CACHE_ROOT" || true

docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --restart unless-stopped \
  --network host \
  -e OCR_PORT="$PORT" \
  -e OCR_VL_ENABLED=0 \
  -e OCR_STRUCTURE_ENABLED=1 \
  -e OCR_STRUCTURE_WARMUP=1 \
  -e OCR_ALLOW_CPU=1 \
  -e OCR_DEVICE=cpu \
  -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  -e PADDLE_PDX_MODEL_SOURCE=modelscope \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e HOME=/home/appuser \
  -v "$CACHE_ROOT/paddlex:/home/appuser/.paddlex" \
  -v "$CACHE_ROOT/paddle:/home/appuser/.cache/paddle" \
  -v "$CACHE_ROOT/huggingface:/home/appuser/.cache/huggingface" \
  -v "$CACHE_ROOT/modelscope:/home/appuser/.cache/modelscope" \
  "$IMAGE"

echo "OCR started: container=$NAME port=$PORT (CPU Structure)"
docker ps --filter "name=$NAME"
