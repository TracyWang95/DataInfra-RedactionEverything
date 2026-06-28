#!/usr/bin/env bash
export CUDA_VISIBLE_DEVICES=1
exec ~/rvenv/vllm/bin/vllm serve ~/redaction-deploy/backend/models/locateanything/locate_qwen2_model \
  --served-model-name locate_qwen2_model --host 0.0.0.0 --port 8093 \
  --enable-prompt-embeds --dtype bfloat16 --max-model-len 8192 --max-num-seqs 4 \
  --gpu-memory-utilization 0.26 --kv-cache-memory-bytes 805306368 --enforce-eager \
  --attention-backend TRITON_ATTN
