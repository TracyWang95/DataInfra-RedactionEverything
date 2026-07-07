LOG=~/la-env-build.log
exec >> "$LOG" 2>&1
set -x
echo "=== VENV LA BUILD $(date) ==="
/home/adminroot/anaconda3/envs/dataInfra/bin/python -m venv ~/rvenv/la && echo ENV_CREATED
P=~/rvenv/la/bin/pip
$P install -U pip -i https://mirrors.aliyun.com/pypi/simple/
echo "=== torch+torchvision cu128 from SJTU ==="
$P install torch torchvision --index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu128 && echo TORCH_OK
~/rvenv/la/bin/python -c "import torch;print('torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo TORCH_BLACKWELL_OK
echo "=== official LA deps from aliyun ==="
$P install opencv-python-headless==4.11.0.86 transformers==4.57.1 numpy==1.25.0 Pillow==11.1.0 peft decord==0.6.0 lmdb==1.7.5 -i https://mirrors.aliyun.com/pypi/simple/ && echo LA_DEPS_OK
$P install fastapi uvicorn httpx einops accelerate -i https://mirrors.aliyun.com/pypi/simple/ && echo SERVER_DEPS_OK
echo "=== MagiAttention (Blackwell sm_120) ==="
cd ~ && rm -rf MagiAttention
git clone -q https://github.com/SandAI-org/MagiAttention.git && cd MagiAttention
git checkout -q v1.0.5
git submodule update --init --recursive 2>&1 | tail -2
$P install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ 2>&1 | tail -2
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=32
echo "=== compiling magi ==="
~/rvenv/la/bin/pip install --no-build-isolation . 2>&1 | tail -10 && echo MAGI_BUILD_DONE
~/rvenv/la/bin/python -c "import magi_attention;print('MAGI_OK',getattr(magi_attention,'__version__','?'))" && echo MAGI_IMPORT_OK || echo MAGI_IMPORT_FAIL
echo "=== LA ALL DONE $(date) ==="
