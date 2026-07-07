LOG=~/vllm-env-build.log
exec >> "$LOG" 2>&1
echo "=== VLLM FINISH $(date) ==="
~/rvenv/vllm/bin/pip install vllm -i https://mirrors.aliyun.com/pypi/simple/ 2>&1 | tail -8
echo "PIP_RC=${PIPESTATUS[0]}"
cd /tmp && ~/rvenv/vllm/bin/python -c "import vllm,torch;print('vllm',vllm.__version__,'torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo VLLM_ENV_OK || echo VLLM_ENV_FAIL
echo "=== VLLM FINISH DONE $(date) ==="
