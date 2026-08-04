#!/bin/bash
# HaS-Image YOLO11 on Ascend NPU (default davinci3 -> host :8081)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

NPU_ID="${YOLO_NPU_ID:-3}"
PORT="${HAS_IMAGE_PORT:-8081}"
NAME="${YOLO_CONTAINER_NAME:-redaction-yolo-npu}"
IMAGE="${YOLO_IMAGE:-redaction-has-image-ascend:latest}"
WEIGHTS="${HAS_IMAGE_WEIGHTS:-$MODELS_DIR/has_image/sensitive_seg_best.pt}"

if [[ ! -f "$WEIGHTS" ]]; then
  echo "FATAL: YOLO weights missing at $WEIGHTS" >&2
  echo "Download: huggingface_hub xuanwulab/HaS_Image_0209_FP32 sensitive_seg_best.pt" >&2
  exit 1
fi

# Always rebuild when FORCE_YOLO_REBUILD=1; otherwise build if missing.
if [[ "${FORCE_YOLO_REBUILD:-0}" == "1" ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build \
    --build-arg "VLLM_ASCEND_IMAGE=$VLLM_ASCEND_IMAGE" \
    -t "$IMAGE" \
    -f "$REPO_ROOT/backend/Dockerfile.has_image.ascend" \
    "$REPO_ROOT/backend"
fi

docker rm -f "$NAME" 2>/dev/null || true
# Driver-only mounts (same pattern as OCR): do NOT overlay host CANN onto this image.
# shellcheck disable=SC2046
docker run -d --name "$NAME" --restart unless-stopped \
  --shm-size=8g \
  --network host \
  -w /app \
  $(npu_docker_common_flags) \
  $(npu_docker_devices "$NPU_ID") \
  -v /usr/local/dcmi:/usr/local/dcmi:ro \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi:ro \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver:ro \
  -e ASCEND_RT_VISIBLE_DEVICES="$NPU_ID" \
  -e HAS_IMAGE_DEVICE=npu:0 \
  -e HAS_IMAGE_PORT="$PORT" \
  -e HAS_IMAGE_WEIGHTS=/models/has_image/sensitive_seg_best.pt \
  -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  -e PYTHONUNBUFFERED=1 \
  -e PYTHONPATH=/app \
  -e QT_QPA_PLATFORM=offscreen \
  -e MPLBACKEND=Agg \
  -v "$(dirname "$WEIGHTS"):/models/has_image:ro" \
  -v "$REPO_ROOT/backend/scripts/has_image_server.py:/app/has_image_server.py:ro" \
  "$IMAGE"

echo "YOLO started: container=$NAME npu=$NPU_ID port=$PORT"
docker ps --filter "name=$NAME"
