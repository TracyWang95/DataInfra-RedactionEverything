cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=0
VLLM=~/anaconda3/envs/vllm-omni-env/bin/vllm
MODEL=~/redaction-deploy/backend/models/has/HaS_Text_0209_0.6B
exec "$VLLM" serve "$MODEL" \
  --served-model-name HaS_Text_0209_0.6B \
  --host 0.0.0.0 --port 8080 \
  --trust-remote-code --dtype bfloat16 \
  --max-model-len 16384 --max-num-batched-tokens 16384 \
  --gpu-memory-utilization 0.90 \
  --default-chat-template-kwargs '{"enable_thinking":false}'
