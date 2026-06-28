export CUDA_VISIBLE_DEVICES=1
export VLLM_USE_MODELSCOPE=true
export PADDLE_PDX_MODEL_SOURCE=modelscope
exec ~/rvenv/vllm/bin/vllm serve PaddlePaddle/PaddleOCR-VL-1.6 --served-model-name PaddleOCR-VL-1.6-0.9B --port 8119 --host 0.0.0.0 --gpu-memory-utilization 0.16 --trust-remote-code
