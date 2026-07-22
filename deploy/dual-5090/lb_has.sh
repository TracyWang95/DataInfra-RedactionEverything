#!/bin/bash
# 2 个 HaS-NER(vLLM) 实例 的负载均衡入口 :29080。自定位到 lb_proxy.py 所在目录，仓库/live 两处都能跑。
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
# nohup 起的非交互 shell PATH 里没有 conda bin，flashinfer JIT 调不到 ninja 会起不来。
export PATH="/home/ubuntu/miniconda3/envs/dataInfra-ocr/bin:$PATH"
export LB_UPSTREAMS="http://127.0.0.1:28080,http://127.0.0.1:28081"
exec /home/ubuntu/miniconda3/envs/dataInfra-ocr/bin/python -m uvicorn lb_proxy:app --host 0.0.0.0 --port 29080 --no-access-log
