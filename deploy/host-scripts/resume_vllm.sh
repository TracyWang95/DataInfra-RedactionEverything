LOG=~/vllm-env-build.log
exec >> "$LOG" 2>&1
echo "=== VLLM RESUME $(date) ==="
~/rvenv/vllm/bin/pip install vllm -i https://mirrors.aliyun.com/pypi/simple/ && echo VLLM_INSTALLED
~/rvenv/vllm/bin/python -c "import vllm,torch;print('vllm',vllm.__version__,'torch',torch.__version__,'cap',torch.cuda.get_device_capability(0))" && echo VLLM_ENV_OK
