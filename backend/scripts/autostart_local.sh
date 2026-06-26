#!/usr/bin/env bash
# 开机自启入口：等待网络/GPU 就绪后启动完整本地栈。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG="${BACKEND_DIR}/logs"
mkdir -p "${LOG}"

exec >>"${LOG}/autostart.log" 2>&1
echo "===== autostart $(date -Is) ====="

# conda / Python（systemd 非交互 shell 默认没有 conda）
CONDA_BASE="${CONDA_BASE:-/home/evalops/anaconda3}"
CONDA_ENV="${CONDA_ENV:-DataInfra_minerU}"
if [[ -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]]; then
  # shellcheck disable=SC1091
  source "${CONDA_BASE}/etc/profile.d/conda.sh"
  conda activate "${CONDA_ENV}"
  export PATH="${CONDA_PREFIX}/bin:${PATH}"
fi

_wait_network() {
  local i=1
  while [[ "${i}" -le 60 ]]; do
    if curl -sf --connect-timeout 2 https://127.0.0.1/ >/dev/null 2>&1 || \
       curl -sf --connect-timeout 2 http://127.0.0.1/ >/dev/null 2>&1 || \
       ping -c1 -W1 127.0.0.1 >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  echo "[autostart] WARN: network wait timed out, continuing anyway"
}

_wait_gpu() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    return 0
  fi
  local i=1
  while [[ "${i}" -le 90 ]]; do
    if nvidia-smi >/dev/null 2>&1; then
      echo "[autostart] GPU ready"
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  echo "[autostart] WARN: GPU not ready after wait; services may fail"
}

_wait_network
_wait_gpu

bash "${SCRIPT_DIR}/restart_all_local.sh"
echo "[autostart] done $(date -Is)"
