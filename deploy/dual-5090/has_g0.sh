#!/bin/bash
# HaS-NER (vLLM) on GPU6, port 28080. Twin of has_g$((1-0)).sh.
cd /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend || exit 1
# nohup 起的非交互 shell PATH 里没有 conda bin，flashinfer JIT 调不到 ninja 会起不来。
export PATH="/home/ubuntu/miniconda3/envs/dataInfra/bin:$PATH"
export CUDA_VISIBLE_DEVICES=6
VLLM=/home/ubuntu/miniconda3/envs/dataInfra/bin/vllm
MODEL=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/models/has/HaS_Text_0209_0.6B
exec "$VLLM" serve "$MODEL"   --served-model-name HaS_Text_0209_0.6B   --host 0.0.0.0 --port 28080   --trust-remote-code --dtype bfloat16   --max-model-len 8192 --max-num-batched-tokens 8192   --gpu-memory-utilization 0.11   --default-chat-template-kwargs '{"enable_thinking":false}'
