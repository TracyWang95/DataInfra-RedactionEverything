#!/bin/bash
# LocateAnything visual features on NPU (default davinci1 -> host :8090)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

NPU_ID="${LA_NPU_ID:-1}"
PORT="${VISUAL_FEATURES_PORT:-8090}"
NAME="${LA_CONTAINER_NAME:-redaction-la-npu}"
MODEL_PATH="${LOCATE_ANYTHING_MODEL:-$MODELS_DIR/locateanything/LocateAnything-3B-HF}"
IMAGE="${LA_IMAGE:-redaction-locateanything-ascend:latest}"

if [[ ! -f "$MODEL_PATH/config.json" ]]; then
  echo "FATAL: model missing at $MODEL_PATH (run: python backend/scripts/download_models.py --only locateanything)" >&2
  exit 1
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build \
    --build-arg "VLLM_ASCEND_IMAGE=$VLLM_ASCEND_IMAGE" \
    -t "$IMAGE" \
    -f "$REPO_ROOT/backend/Dockerfile.locateanything.ascend" \
    "$REPO_ROOT/backend"
fi

docker rm -f "$NAME" 2>/dev/null || true
# shellcheck disable=SC2046
docker run -d --name "$NAME" --restart unless-stopped \
  --shm-size=16g \
  --network host \
  -w /app \
  $(npu_docker_common_flags) \
  $(npu_docker_devices "$NPU_ID") \
  $(npu_docker_volumes) \
  -e ASCEND_RT_VISIBLE_DEVICES="$NPU_ID" \
  -e ACCEL_DEVICE=npu \
  -e LA_DEVICE=npu \
  -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  -e LOCATE_ANYTHING_MODEL=/models/locateanything \
  -e LOCATE_ANYTHING_BACKEND=auto \
  -e LOCATE_ANYTHING_DTYPE=bfloat16 \
  -e LOCATE_ANYTHING_PORT="$PORT" \
  -e PYTHONUNBUFFERED=1 \
  -e PYTHONPATH=/app \
  -v "$MODEL_PATH:/models/locateanything:ro" \
  "$IMAGE"

echo "LA started: container=$NAME npu=$NPU_ID port=$PORT"
docker ps --filter "name=$NAME"
