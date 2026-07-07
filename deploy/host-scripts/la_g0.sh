cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=0
export PYTHONPATH=~/redaction-deploy/backend
export LOCATE_ANYTHING_MODEL=~/redaction-deploy/backend/models/locateanything/LocateAnything-3B-HF
export LOCATE_ANYTHING_MODEL_NAME=LocateAnything-3B
export LOCATE_ANYTHING_BACKEND=hf
export LOCATE_ANYTHING_DTYPE=bfloat16
export LOCATE_ANYTHING_PORT=8090
export LOCATE_ANYTHING_GENERATION_MODE=hybrid
export LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
export LOCATE_ANYTHING_MAX_IMAGE_SIDE=1280
export LOCATE_ANYTHING_TEMPERATURE=0.1
export LOCATE_ANYTHING_VLLM_URL=http://127.0.0.1:8092/v1/completions
export LOCATE_ANYTHING_FAST_FIRST=0
exec ~/rvenv/la/bin/python scripts/locate_anything_server.py \
  --backend hf --model "$LOCATE_ANYTHING_MODEL" --dtype bfloat16 --port 8090
