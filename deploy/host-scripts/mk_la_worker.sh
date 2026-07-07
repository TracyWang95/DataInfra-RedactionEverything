LOG=~/la-env-build.log
exec >> "$LOG" 2>&1
set -x
echo "=== BUILD LA ENV $(date) ==="
source ~/anaconda3/etc/profile.d/conda.sh
conda create -n redact-la python=3.11 -y && echo "ENV_CREATED"
conda activate redact-la
pip install -q -U pip
echo "=== torch cu128 (Blackwell) ==="
pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu128 && echo "TORCH_OK"
python -c "import torch;print('torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo "TORCH_BLACKWELL_OK"
echo "=== official LA deps ==="
pip install -q opencv-python-headless==4.11.0.86 transformers==4.57.1 numpy==1.25.0 Pillow==11.1.0 peft decord==0.6.0 lmdb==1.7.5 && echo "LA_DEPS_OK"
pip install -q fastapi uvicorn httpx einops accelerate && echo "SERVER_DEPS_OK"
echo "=== MagiAttention (Blackwell MTP accel) ==="
cd ~ && rm -rf MagiAttention
git clone -q https://github.com/SandAI-org/MagiAttention.git && cd MagiAttention
git checkout -q v1.0.5
git submodule update --init --recursive 2>&1 | tail -3
pip install -q -r requirements.txt 2>&1 | tail -3
export CUDA_HOME=/usr/local/cuda-12.8
export PATH=$CUDA_HOME/bin:$PATH
export TORCH_CUDA_ARCH_LIST="12.0"
export MAX_JOBS=32
echo "=== compiling magi (this is the long part) ==="
pip install --no-build-isolation . 2>&1 | tail -8 && echo "MAGI_BUILD_DONE"
python -c "import magi_attention; print('MAGI_OK', getattr(magi_attention,'__version__','?'))" && echo "MAGI_IMPORT_OK" || echo "MAGI_IMPORT_FAIL"
echo "=== ALL DONE $(date) ==="
