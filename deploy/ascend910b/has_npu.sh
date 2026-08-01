#!/bin/bash
# HaS Text NER via vllm-ascend on NPU (default davinci0 -> host :8080)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_npu.sh"

NPU_ID="${HAS_NPU_ID:-0}"
PORT="${NER_PORT:-8080}"
NAME="${HAS_CONTAINER_NAME:-redaction-has-npu}"
MODEL_PATH="${HAS_TEXT_HF_MODEL_PATH:-$MODELS_DIR/has/HaS_Text_0209_0.6B}"

if [[ ! -f "$MODEL_PATH/config.json" ]]; then
  echo "FATAL: model missing at $MODEL_PATH (run: python backend/scripts/download_models.py --only has)" >&2
  exit 1
fi

docker rm -f "$NAME" 2>/dev/null || true
# Keep image ENTRYPOINT (sources CANN). Workdir /tmp avoids shadowing installed vllm.
# Patch tokenizer compat for newer transformers missing all_special_tokens_extended.
# shellcheck disable=SC2046
docker run -d --name "$NAME" --restart unless-stopped \
  --shm-size=16g \
  --network host \
  -w /tmp \
  $(npu_docker_common_flags) \
  $(npu_docker_devices "$NPU_ID") \
  $(npu_docker_volumes) \
  -e ASCEND_RT_VISIBLE_DEVICES="$NPU_ID" \
  -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  -e VLLM_USE_MODELSCOPE="${VLLM_USE_MODELSCOPE:-true}" \
  -e PYTHONUNBUFFERED=1 \
  -e PYTHONPATH=/tmp/has_patches \
  -v "$MODEL_PATH:/models/has:ro" \
  -v "$SCRIPT_DIR/has_patches:/tmp/has_patches:ro" \
  "$VLLM_ASCEND_IMAGE" \
  bash -lc "pip install -q 'setuptools<81' && \
    exec python -m vllm.entrypoints.openai.api_server \
    --model /models/has \
    --served-model-name HaS_Text_0209_0.6B \
    --host 0.0.0.0 \
    --port ${PORT} \
    --trust-remote-code \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-batched-tokens 4096 \
    --gpu-memory-utilization 0.35 \
    --enforce-eager"

echo "HAS started: container=$NAME npu=$NPU_ID port=$PORT"
docker ps --filter "name=$NAME"
