#!/bin/bash
cd /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend || exit 1
# nohup 起的非交互 shell PATH 里没有 conda bin，flashinfer JIT 调不到 ninja 会起不来。
export PATH="/home/ubuntu/miniconda3/envs/dataInfra-ocr/bin:$PATH"
export CUDA_VISIBLE_DEVICES=7
export PYTHONPATH=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend
export OCR_VL_ENABLED=1 OCR_VL_BACKEND=vllm-server
export OCR_VLLM_URL=http://127.0.0.1:28119/v1
export OCR_VL_API_MODEL_NAME=PaddleOCR-VL-1.6-0.9B
export OCR_STRUCTURE_ENABLED=true OCR_STRUCTURE_PRIMARY=true OCR_STRUCTURE_WARMUP=1
export OCR_VL_MAX_CONCURRENCY=128
export OCR_MAX_IMAGE_SIDE=2048 OCR_PORT=28083 PADDLE_PDX_MODEL_SOURCE=modelscope
export OCR_PEER_URL=http://127.0.0.1:28082
exec /home/ubuntu/miniconda3/envs/dataInfra-ocr/bin/python scripts/ocr_server.py
