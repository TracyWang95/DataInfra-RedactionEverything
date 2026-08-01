#!/bin/bash
# vLLM venv：pip 清华源；PyTorch CUDA wheel 阿里云
LOG=~/vllm-env-build.log
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/scripts/cn_mirrors.env"; set +a
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL_CU128:-https://mirrors.aliyun.com/pytorch-wheels/cu128}"
exec >> "$LOG" 2>&1
set -x
echo "=== VENV VLLM BUILD $(date) ==="
/home/adminroot/anaconda3/envs/dataInfra/bin/python -m venv ~/rvenv/vllm && echo ENV_CREATED
P=~/rvenv/vllm/bin/pip
$P install -U pip -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST"
echo "=== torch from $PYTORCH_INDEX_URL ==="
$P install torch --index-url "$PYTORCH_INDEX_URL" && echo TORCH_OK
~/rvenv/vllm/bin/python -c "import torch;print('torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo TORCH_BLACKWELL_OK
echo "=== vllm from Tsinghua PyPI ==="
$P install vllm -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" && echo VLLM_INSTALLED
~/rvenv/vllm/bin/python -c "import vllm,torch;print('vllm',vllm.__version__,'torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo VLLM_ENV_OK
echo "=== VLLM DONE $(date) ==="
