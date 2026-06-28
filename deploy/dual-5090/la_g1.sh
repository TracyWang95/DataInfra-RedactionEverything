cd ~/redaction-deploy/backend
export CUDA_VISIBLE_DEVICES=1 PYTHONPATH=~/redaction-deploy/backend
export LOCATE_ANYTHING_BACKEND=hf LOCATE_ANYTHING_DTYPE=bfloat16 LOCATE_ANYTHING_PORT=8091
export LOCATE_ANYTHING_GENERATION_MODE=hybrid LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
export LOCATE_ANYTHING_MAX_IMAGE_SIDE=1280 LOCATE_ANYTHING_TEMPERATURE=0.1 LOCATE_ANYTHING_VLLM_URL=http://127.0.0.1:8093/v1/completions
export LOCATE_ANYTHING_FAST_FIRST=0
exec ~/rvenv/la/bin/python scripts/locate_anything_server.py --backend hf \
  --model ~/redaction-deploy/backend/models/locateanything/LocateAnything-3B-HF --dtype bfloat16 --port 8091
