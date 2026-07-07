LOG=~/vllm-env-build.log
exec >> "$LOG" 2>&1
echo "=== BUILD VLLM ENV $(date) ==="
source ~/anaconda3/etc/profile.d/conda.sh
conda create -n redact-vllm python=3.12 -y && echo "ENV_CREATED"
conda activate redact-vllm
pip install -q -U pip
echo "=== pip install vllm (pulls matching torch cu128) ==="
pip install -q vllm 2>&1 | tail -5 && echo "VLLM_INSTALLED"
python -c "import vllm, torch; print('vllm', vllm.__version__, 'torch', torch.__version__, 'cap', torch.cuda.get_device_capability(0))" && echo "VLLM_ENV_OK"
echo "=== DONE $(date) ==="
