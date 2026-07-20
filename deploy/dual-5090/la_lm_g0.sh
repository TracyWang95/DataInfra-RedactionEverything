#!/bin/bash
# LA LM (vLLM Qwen2 decoder) GPU6 :28092. flashinfer 原生JIT编译(CUDA_HOME+PATH
# 指到系统cuda-13.0的nvcc + conda的ninja)。
cd /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend || exit 1
export CUDA_VISIBLE_DEVICES=6
export CUDA_HOME=/usr/local/cuda
export PATH=/usr/local/cuda/bin:$HOME/miniconda3/envs/dataInfra/bin:$PATH
export VLLM_USE_MODELSCOPE=false
exec ~/miniconda3/envs/dataInfra/bin/vllm serve /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/models/locateanything/locate_qwen2_model   --served-model-name locate_qwen2_model --enable-prompt-embeds   --host 127.0.0.1 --port 28092 --gpu-memory-utilization 0.25   --max-model-len 8192 --kv-cache-memory-bytes 805306368 --enforce-eager --max-num-seqs 4 --trust-remote-code
