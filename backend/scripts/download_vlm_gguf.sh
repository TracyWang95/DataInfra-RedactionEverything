#!/usr/bin/env bash
# 从国内 HF 镜像下载 GLM-4.6V-Flash GGUF（供 llama-server 使用，避免 llama-server 无 HTTPS 支持）
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/hf_mirror_env.sh"

REPO="ggml-org/GLM-4.6V-Flash-GGUF"
MODEL_FILE="${VLM_GGUF_FILE:-GLM-4.6V-Flash-Q4_K_M.gguf}"
MMPROJ_FILE="${VLM_MMPROJ_FILE:-mmproj-GLM-4.6V-Flash-Q8_0.gguf}"
DEST="${VLM_MODELS_DIR:-${BACKEND_DIR}/models/vlm}"
BASE="${HF_MIRROR_BASE%/}/${REPO}/resolve/main"

mkdir -p "${DEST}"

_download() {
  local name="$1"
  local out="${DEST}/${name}"
  if [[ -f "${out}" && -s "${out}" ]]; then
    echo "[download] 已存在，跳过: ${out}"
    return 0
  fi
  local url="${BASE}/${name}"
  echo "[download] <- ${url}"
  echo "[download] -> ${out}"
  if command -v wget >/dev/null 2>&1; then
    wget -c --show-progress -O "${out}.part" "${url}"
    mv -f "${out}.part" "${out}"
  elif command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 -C - -o "${out}.part" "${url}"
    mv -f "${out}.part" "${out}"
  else
    echo "[download] FATAL: 需要 wget 或 curl" >&2
    exit 1
  fi
}

_download "${MODEL_FILE}"
_download "${MMPROJ_FILE}"

echo "[download] 完成。启动 VLM:"
echo "  export GLM_FLASH_MODEL_FOR_SERVER=${DEST}/${MODEL_FILE}"
echo "  export GLM_FLASH_MMPROJ_FOR_SERVER=${DEST}/${MMPROJ_FILE}"
echo "  ./scripts/run_vlm_llama_server.sh"
