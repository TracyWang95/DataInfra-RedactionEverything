cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=0
VLLM=~/rvenv/vllm/bin/vllm
MODEL=~/redaction-deploy/backend/models/has/HaS_Text_0209_0.6B
exec "$VLLM" serve "$MODEL" \
  --served-model-name HaS_Text_0209_0.6B \
  --host 0.0.0.0 --port 8080 \
  --trust-remote-code --dtype bfloat16 \
  --max-model-len 8192 --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.11 \
  --default-chat-template-kwargs '{"enable_thinking":false}'
