#!/bin/bash
# has_image (YOLO) on GPU6, port 28140. Twin of yolo_g$((1-0)).sh.
cd /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/scripts || exit 1
# nohup 起的非交互 shell PATH 里没有 conda bin，flashinfer JIT 调不到 ninja 会起不来。
export PATH="/home/ubuntu/miniconda3/envs/dataInfra/bin:$PATH"
export CUDA_VISIBLE_DEVICES=6
export PYTHONPATH=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend
export HAS_IMAGE_PORT=28140
export HAS_IMAGE_WEIGHTS=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/models/has_image/best.pt
exec /home/ubuntu/miniconda3/envs/dataInfra/bin/python has_image_server.py
