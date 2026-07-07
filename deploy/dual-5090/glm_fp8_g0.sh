cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=0
exec /home/adminroot/rvenv/vllm/bin/vllm serve /home/adminroot/judge_models/GLM-4.6V-Flash \
  --served-model-name glm-fp8 --host 127.0.0.1 --port 8120 \
  --quantization fp8 --gpu-memory-utilization 0.40 \
  --max-model-len 8192 --max-num-seqs 4 --trust-remote-code \
  --default-chat-template-kwargs '{"enable_thinking":false}'
