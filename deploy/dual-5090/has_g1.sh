cd ~/redaction-deploy/backend
export CUDA_VISIBLE_DEVICES=1
exec ~/rvenv/vllm/bin/vllm serve ~/redaction-deploy/backend/models/has/HaS_Text_0209_0.6B \
  --served-model-name HaS_Text_0209_0.6B --host 0.0.0.0 --port 8081 \
  --trust-remote-code --dtype bfloat16 --max-model-len 8192 --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.11 --default-chat-template-kwargs '{"enable_thinking":false}'
