~/rvenv/vllm/bin/pip install -q modelscope -i https://mirrors.aliyun.com/pypi/simple/ > /tmp/ms_install.log 2>&1
echo done_install >> /tmp/ms_install.log
fuser -k 8118/tcp 2>/dev/null
setsid nohup bash ~/vl_serve.sh > /tmp/vl_serve.log 2>&1 </dev/null &
