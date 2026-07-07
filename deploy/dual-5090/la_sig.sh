cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=1
export PYTHONPATH=~/redaction-deploy/backend
export LOCATE_ANYTHING_MODEL=~/redaction-deploy/backend/models/locateanything/LocateAnything-3B-HF
export LOCATE_ANYTHING_MODEL_NAME=LocateAnything-3B
export LOCATE_ANYTHING_BACKEND=hf
export LOCATE_ANYTHING_DTYPE=bfloat16
export LOCATE_ANYTHING_PORT=8091
export LOCATE_ANYTHING_GENERATION_MODE=hybrid
export LOCATE_ANYTHING_MAX_NEW_TOKENS=2048
export LOCATE_ANYTHING_MAX_IMAGE_SIDE=1024
export LOCATE_ANYTHING_MIN_IMAGE_SIDE=1024
export LOCATE_ANYTHING_TEMPERATURE=0.1
export LOCATE_ANYTHING_FAST_FIRST=0
exec ~/rvenv/la/bin/python scripts/locate_anything_server.py --backend hf --model "$LOCATE_ANYTHING_MODEL" --dtype bfloat16 --port 8091
