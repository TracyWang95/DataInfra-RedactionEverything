#!/bin/bash
# 部署引导：经阿里云 Docker 加速器拉取镜像 + 下载模型（魔搭 / HF 镜像）
cd ~/redaction-deploy || exit 1
LOG=~/deploy-bootstrap.log
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/scripts/cn_mirrors.env"; set +a
exec >> "$LOG" 2>&1
echo "=== START $(date) ==="

VLLM_TAG="vllm/vllm-openai:v0.19.1"
echo "=== [1/4] pull vllm image (registry-mirrors: ${DOCKER_REGISTRY_MIRROR}) ==="
# 依赖本机已配置阿里云加速器：sudo bash scripts/configure_docker_mirror.sh
docker pull "${VLLM_TAG}" && echo "VLLM_IMAGE_OK" || echo "VLLM_IMAGE_FAIL"

echo "=== [2/4] install modelscope + huggingface_hub (清华 pip) ==="
python3 -m pip install -q --break-system-packages \
  -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" \
  modelscope 'huggingface_hub>=0.25' && echo "HUB_OK" || echo "HUB_FAIL"

mkdir -p backend/models/has backend/models/locateanything
echo "=== [3-4/4] download models (ModelScope -> HF mirror) ==="
python3 "$REPO_ROOT/backend/scripts/download_models.py"
echo "=== ALL DONE $(date) ==="
