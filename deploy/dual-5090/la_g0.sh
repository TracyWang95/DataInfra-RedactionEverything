#!/bin/bash
export PATH=/home/ubuntu/miniconda3/envs/dataInfra-la/bin:$PATH
cd /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend || exit 1
export CUDA_VISIBLE_DEVICES=6
export PYTHONPATH=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export LOCATE_ANYTHING_MODEL=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/models/locateanything/LocateAnything-3B-HF
export LOCATE_ANYTHING_MODEL_NAME=LocateAnything-3B
export LOCATE_ANYTHING_BACKEND=hf
export LOCATE_ANYTHING_DTYPE=bfloat16
export LOCATE_ANYTHING_PORT=28090
export LOCATE_ANYTHING_GENERATION_MODE=slow
export LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
export LOCATE_ANYTHING_MAX_IMAGE_SIDE=1280
export LOCATE_ANYTHING_MIN_IMAGE_SIDE=1280
export LOCATE_ANYTHING_FAST_FIRST=0
export LOCATE_ANYTHING_VLLM_URL=http://127.0.0.1:28092/v1/completions
export LOCATE_ANYTHING_VLLM_SAMPLES=5
exec /home/ubuntu/miniconda3/envs/dataInfra-la/bin/python scripts/locate_anything_server.py \
  --backend hf --model "$LOCATE_ANYTHING_MODEL" --dtype bfloat16 --port 28090
