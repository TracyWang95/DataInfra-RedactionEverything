LOG=~/vllm-env-build.log
exec >> "$LOG" 2>&1
set -x
echo "=== VENV VLLM BUILD $(date) ==="
/home/adminroot/anaconda3/envs/dataInfra/bin/python -m venv ~/rvenv/vllm && echo ENV_CREATED
P=~/rvenv/vllm/bin/pip
$P install -U pip -i https://mirrors.aliyun.com/pypi/simple/
echo "=== torch cu128 from SJTU ==="
$P install torch --index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu128 && echo TORCH_OK
~/rvenv/vllm/bin/python -c "import torch;print('torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo TORCH_BLACKWELL_OK
echo "=== vllm from aliyun ==="
$P install vllm -i https://mirrors.aliyun.com/pypi/simple/ && echo VLLM_INSTALLED
~/rvenv/vllm/bin/python -c "import vllm,torch;print('vllm',vllm.__version__,'torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo VLLM_ENV_OK
echo "=== VLLM DONE $(date) ==="
