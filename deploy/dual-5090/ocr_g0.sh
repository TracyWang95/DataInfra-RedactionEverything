#!/bin/bash
# OCR (PP-StructureV3 + PP-OCRv6) on GPU0, port 8082. Twin of ocr_g1.sh.
cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=0 PYTHONPATH=~/redaction-deploy/backend
export OCR_VL_ENABLED=1 OCR_VL_BACKEND=vllm-server OCR_VLLM_URL=http://127.0.0.1:8118/v1 OCR_VL_API_MODEL_NAME=PaddleOCR-VL-1.6-0.9B
export OCR_STRUCTURE_ENABLED=true OCR_STRUCTURE_PRIMARY=true OCR_STRUCTURE_WARMUP=1
export OCR_MAX_IMAGE_SIDE=2048 OCR_PORT=8082 PADDLE_PDX_MODEL_SOURCE=modelscope
export OCR_PEER_URL=http://127.0.0.1:8083
exec ~/anaconda3/envs/dataInfra/bin/python scripts/ocr_server.py
