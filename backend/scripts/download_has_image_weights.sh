#!/usr/bin/env bash
# 下载 HaS Image YOLO 权重到 has_image_server 默认路径。
# 仓库: https://huggingface.co/xuanwulab/HaS_Image_0209_FP32
# 文件: sensitive_seg_best.pt
#
# 国内可将 HF_MIRROR_BASE 设为 https://hf-mirror.com（与浏览器访问 hf-mirror 一致）。
#
# 用法（在 backend 目录）：
#   HF_MIRROR_BASE=https://hf-mirror.com ./scripts/download_has_image_weights.sh
#
# 下载完成后在 backend 目录重启（勿复制本注释里的中文整行到终端）：
#   python3 scripts/has_image_server.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/hf_mirror_env.sh"
REPO_PATH="xuanwulab/HaS_Image_0209_FP32"
FILENAME="sensitive_seg_best.pt"
DEST_DIR="${DEST_DIR:-${BACKEND_DIR}/models/has_image}"
OUT="${DEST_DIR}/${FILENAME}"

URL="${HF_MIRROR_BASE%/}/${REPO_PATH}/resolve/main/${FILENAME}"

mkdir -p "${DEST_DIR}"

if [[ -f "${OUT}" ]]; then
  echo "[download] 已存在，跳过: ${OUT}"
  exit 0
fi

echo "[download] -> ${OUT}"
echo "[download] <- ${URL}"

if command -v wget >/dev/null 2>&1; then
  wget -c --show-progress -O "${OUT}.part" "${URL}"
  mv -f "${OUT}.part" "${OUT}"
elif command -v curl >/dev/null 2>&1; then
  curl -fL --retry 3 --retry-delay 2 -o "${OUT}.part" "${URL}"
  mv -f "${OUT}.part" "${OUT}"
else
  echo "错误: 需要 wget 或 curl" >&2
  exit 1
fi

if [[ ! -s "${OUT}" ]]; then
  echo "错误: 下载结果为空，请检查网络或 HF_MIRROR_BASE" >&2
  rm -f "${OUT}"
  exit 1
fi

echo "[download] 完成: ${OUT}"
echo "[download] 下一步（在 backend 目录执行，仅复制下面引号内命令）:"
echo "    python3 scripts/has_image_server.py"
