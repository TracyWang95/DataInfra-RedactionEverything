#!/bin/bash
export PATH=/home/ubuntu/miniconda3/envs/dataInfra/bin:$PATH
export CUDA_VISIBLE_DEVICES=7
export VLLM_USE_MODELSCOPE=true
export PADDLE_PDX_MODEL_SOURCE=modelscope
exec /home/ubuntu/miniconda3/envs/dataInfra/bin/vllm serve /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/models/paddleocr-vl/PaddleOCR-VL-1.6 \
  --served-model-name PaddleOCR-VL-1.6-0.9B --port 28119 --host 0.0.0.0 \
  --gpu-memory-utilization 0.13 --max-model-len 16384 --trust-remote-code
