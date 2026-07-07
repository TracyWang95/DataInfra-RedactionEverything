#!/usr/bin/env bash
# GPU 采样：benchmark 期间每 2s 记录双卡利用率/显存。
# 用法: LABEL=baseline bash gpu_sample.sh   (Ctrl-C/kill 停止)
LABEL="${LABEL:-run}"
OUT="$HOME/logs/gpu_${LABEL}.csv"
echo "timestamp,index,util_pct,mem_used_mb" > "$OUT"
while true; do
  nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used --format=csv,noheader,nounits >> "$OUT"
  sleep 2
done
