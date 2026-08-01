#!/bin/bash
# Shared NPU docker device mounts for Ascend 910B.
# shellcheck disable=SC2034

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/scripts/cn_mirrors.env"; set +a

VLLM_ASCEND_IMAGE="${VLLM_ASCEND_IMAGE:-openeuler/vllm-ascend:0.11.0rc0-torch_npu2.5.1-cann8.1.rc1-python3.10-oe2403sp4}"
MODELS_DIR="${MODELS_DIR:-$REPO_ROOT/backend/models}"

npu_docker_devices() {
  # Mount requested card plus manager nodes. Prefer privileged runs for driver ioctls.
  local id="${1:-0}"
  echo "--device /dev/davinci${id}"
  echo "--device /dev/davinci_manager"
  echo "--device /dev/devmm_svm"
  echo "--device /dev/hisi_hdc"
}

npu_docker_volumes() {
  echo "-v /usr/local/dcmi:/usr/local/dcmi"
  echo "-v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi"
  echo "-v /usr/local/sbin/npu-smi:/usr/local/sbin/npu-smi"
  echo "-v /usr/local/Ascend/driver:/usr/local/Ascend/driver:ro"
  echo "-v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info:ro"
  echo "-v /etc/ascend_install.info:/etc/ascend_install.info:ro"
  # Host CANN (matches driver 25.2.3 + toolkit 8.3.RC2)
  if [[ -d /usr/local/Ascend/ascend-toolkit ]]; then
    echo "-v /usr/local/Ascend/ascend-toolkit:/usr/local/Ascend/ascend-toolkit:ro"
  fi
  if [[ -d /usr/local/Ascend/nnal ]]; then
    echo "-v /usr/local/Ascend/nnal:/usr/local/Ascend/nnal:ro"
  fi
}

npu_docker_common_flags() {
  echo "--privileged"
  echo "--ipc=host"
}
