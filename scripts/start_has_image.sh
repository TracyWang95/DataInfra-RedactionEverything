#!/usr/bin/env bash
# HaS Image (YOLO11) — port 8081
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_ROOT="$ROOT_DIR/backend"
ENV_NAME="${LEGAL_REDACTION_CONDA_ENV:-legal-redaction}"

# --- Locate conda ---
find_conda_root() {
    if [[ -n "${CONDA_ROOT:-}" && -x "$CONDA_ROOT/bin/conda" ]]; then
        echo "$CONDA_ROOT"; return
    fi
    for c in "$HOME/anaconda3" "$HOME/miniconda3" "/opt/conda" "/opt/anaconda3" "/opt/miniconda3"; do
        if [[ -x "$c/bin/conda" ]]; then echo "$c"; return; fi
    done
    local cmd
    cmd=$(command -v conda 2>/dev/null || true)
    if [[ -n "$cmd" ]]; then
        echo "$(dirname "$(dirname "$cmd")")"; return
    fi
    echo ""
}

CONDA_ROOT_DIR=$(find_conda_root)
CONDA_EXE="${CONDA_ROOT_DIR:+$CONDA_ROOT_DIR/bin/conda}"

if [[ -z "$CONDA_EXE" || ! -x "$CONDA_EXE" ]]; then
    echo "[ERR] conda not found; set CONDA_ROOT or add conda to PATH"
    exit 1
fi

# --- Resolve weights ---
if [[ -z "${HAS_IMAGE_WEIGHTS:-}" ]]; then
    WORKSPACE_ROOT="$(dirname "$ROOT_DIR")"
    CANDIDATES=()
    if [[ -n "${HAS_MODELS_DIR:-}" && -n "${HAS_MODELS_DIR}" ]]; then
        CANDIDATES+=("${HAS_MODELS_DIR}/sensitive_seg_best.pt")
    fi
    CANDIDATES+=("/data/has_models/sensitive_seg_best.pt")
    CANDIDATES+=("$WORKSPACE_ROOT/has_models/sensitive_seg_best.pt")

    for pt in "${CANDIDATES[@]}"; do
        if [[ -f "$pt" ]]; then
            export HAS_IMAGE_WEIGHTS="$pt"
            break
        fi
    done
fi

DEFAULT_REPO_WEIGHTS="$BACKEND_ROOT/models/has_image/sensitive_seg_best.pt"
if [[ -z "${HAS_IMAGE_WEIGHTS:-}" && ! -f "$DEFAULT_REPO_WEIGHTS" ]]; then
    echo "HaS Image: weights sensitive_seg_best.pt not found; 8081 may report ready=false"
    echo "  Download: conda run -n $ENV_NAME python $ROOT_DIR/scripts/download_has_image_weights.py"
fi

echo "HaS Image: conda run -n $ENV_NAME python has_image_server.py"
echo "HaS Image: HAS_IMAGE_WEIGHTS=${HAS_IMAGE_WEIGHTS:-<not set>}"

mkdir -p "$ROOT_DIR/logs"
cd "$BACKEND_ROOT"
nohup "$CONDA_EXE" run -n "$ENV_NAME" --no-capture-output \
    python has_image_server.py \
    > "$ROOT_DIR/logs/has_image_stdout.log" 2> "$ROOT_DIR/logs/has_image_stderr.log" &

echo "HaS Image: started PID=$! port 8081"
exit 0
