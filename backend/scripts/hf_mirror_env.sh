# 国内 Hugging Face / ModelScope 镜像（被各启动脚本 source，勿直接执行）
# 覆盖示例: HF_ENDPOINT=https://hf-mirror.com ./scripts/run_vlm_llama_server.sh
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HUGGINGFACE_HUB_ENDPOINT="${HUGGINGFACE_HUB_ENDPOINT:-${HF_ENDPOINT}}"
export HF_HUB_DOWNLOAD_TIMEOUT="${HF_HUB_DOWNLOAD_TIMEOUT:-600}"
export HF_HUB_ETAG_TIMEOUT="${HF_HUB_ETAG_TIMEOUT:-120}"
export MODELSCOPE_DOMAIN="${MODELSCOPE_DOMAIN:-www.modelscope.cn}"
export HF_MIRROR_BASE="${HF_MIRROR_BASE:-${HF_ENDPOINT}}"
