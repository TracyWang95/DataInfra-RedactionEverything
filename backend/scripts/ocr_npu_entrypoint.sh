#!/bin/bash
# Source image-bundled Ascend CANN 8.0 + ATB, then exec OCR server.
set -eo pipefail

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
export PATH="${PATH:-}"

if [[ -f /usr/local/Ascend/ascend-toolkit/set_env.sh ]]; then
  # shellcheck disable=SC1091
  source /usr/local/Ascend/ascend-toolkit/set_env.sh
fi

# paddle-custom-npu 3.2.0 links against the pre-cxx11 ABI ATB tree.
if [[ -f /usr/local/Ascend/nnal/atb/set_env.sh ]]; then
  # shellcheck disable=SC1091
  source /usr/local/Ascend/nnal/atb/set_env.sh --cxx_abi=0
fi
if [[ -f /usr/local/Ascend/nnal/asdsip/set_env.sh ]]; then
  # shellcheck disable=SC1091
  source /usr/local/Ascend/nnal/asdsip/set_env.sh || true
fi

# ARM TLS: sklearn/opencv libgomp + GLdispatch must be preloaded first.
PRELOAD_PARTS=()
for cand in \
  /usr/local/lib/python3.10/dist-packages/scikit_learn.libs/libgomp*.so* \
  /usr/local/lib/python3.10/site-packages/scikit_learn.libs/libgomp*.so*
do
  # shellcheck disable=SC2086
  for f in $cand; do
    if [[ -f "$f" ]]; then
      PRELOAD_PARTS+=("$f")
      break 2
    fi
  done
done
for f in \
  /usr/lib/aarch64-linux-gnu/libGLdispatch.so.0 \
  /usr/lib/aarch64-linux-gnu/libgomp.so.1
do
  [[ -f "$f" ]] && PRELOAD_PARTS+=("$f")
done
if ((${#PRELOAD_PARTS[@]})); then
  joined="$(IFS=:; echo "${PRELOAD_PARTS[*]}")"
  export LD_PRELOAD="${joined}${LD_PRELOAD:+:$LD_PRELOAD}"
fi

# Static-inference stability flags for Ascend (PaddleOCR #16965).
export FLAGS_npu_jit_compile="${FLAGS_npu_jit_compile:-false}"
export FLAGS_npu_scale_aclnn="${FLAGS_npu_scale_aclnn:-True}"
export FLAGS_npu_split_aclnn="${FLAGS_npu_split_aclnn:-True}"
export FLAGS_use_stride_kernel="${FLAGS_use_stride_kernel:-0}"

PY_BIN="$(command -v python3 || command -v python)"
PY_SITE="$("$PY_BIN" -c 'import site; print(site.getsitepackages()[0])')"
export LD_LIBRARY_PATH="${PY_SITE}/paddle/base:${PY_SITE}/paddle_custom_device:${LD_LIBRARY_PATH:-}"

export HOME="${HOME:-/home/appuser}"
mkdir -p "$HOME/.paddlex" "$HOME/.cache"

exec "$@"
