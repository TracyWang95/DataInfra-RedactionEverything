#!/bin/bash
# 模型下载：魔搭优先，失败则走 Hugging Face 镜像（hf-mirror.com）
cd ~/redaction-deploy || exit 1
LOG=~/models-dl.log
PY=~/anaconda3/envs/dataInfra/bin/python
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/scripts/cn_mirrors.env"; set +a
exec >> "$LOG" 2>&1
echo "=== START $(date) ==="
"$PY" -m pip install -q -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" \
  modelscope 'huggingface_hub>=0.25' 2>&1 | tail -3
mkdir -p backend/models/has backend/models/locateanything
"$PY" "$REPO_ROOT/backend/scripts/download_models.py"
echo "=== ALL DONE $(date) ==="
du -sh backend/models/has/* backend/models/locateanything/* 2>/dev/null
