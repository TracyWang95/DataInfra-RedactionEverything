#!/bin/bash
# LocateAnything venv：pip 清华源；PyTorch CUDA wheel 阿里云
LOG=~/la-env-build.log
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/scripts/cn_mirrors.env"; set +a
# 本机构建用 cu128；可被环境变量覆盖
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL_CU128:-https://mirrors.aliyun.com/pytorch-wheels/cu128}"
exec >> "$LOG" 2>&1
set -x
echo "=== VENV LA BUILD $(date) ==="
/home/adminroot/anaconda3/envs/dataInfra/bin/python -m venv ~/rvenv/la && echo ENV_CREATED
P=~/rvenv/la/bin/pip
$P install -U pip -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST"
echo "=== torch+torchvision from $PYTORCH_INDEX_URL ==="
$P install torch torchvision --index-url "$PYTORCH_INDEX_URL" && echo TORCH_OK
~/rvenv/la/bin/python -c "import torch;print('torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo TORCH_BLACKWELL_OK
echo "=== LA deps from Tsinghua PyPI ==="
$P install opencv-python-headless==4.11.0.86 transformers==4.57.1 numpy==1.25.0 Pillow==11.1.0 peft decord==0.6.0 lmdb==1.7.5 \
  -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" && echo LA_DEPS_OK
$P install fastapi uvicorn httpx einops accelerate modelscope \
  -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" && echo SERVER_DEPS_OK
echo "=== MagiAttention (Blackwell sm_120) ==="
cd ~ && rm -rf MagiAttention
if ! git clone -q https://ghproxy.net/https://github.com/SandAI-org/MagiAttention.git MagiAttention; then
  git clone -q https://github.com/SandAI-org/MagiAttention.git MagiAttention
fi
cd MagiAttention
git checkout -q v1.0.5
git submodule update --init --recursive 2>&1 | tail -2
$P install -r requirements.txt -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" 2>&1 | tail -2
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=32
echo "=== compiling magi ==="
~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -10 && echo MAGI_BUILD_DONE
~/rvenv/la/bin/python -c "import magi_attention;print('MAGI_OK',getattr(magi_attention,'__version__','?'))" && echo MAGI_IMPORT_OK || echo MAGI_IMPORT_FAIL
echo "=== LA ALL DONE $(date) ==="
