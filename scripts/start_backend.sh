#!/usr/bin/env bash
# FastAPI main backend — port 8000 (conda run)
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

echo "Backend: conda run -n $ENV_NAME python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

mkdir -p "$ROOT_DIR/logs"
cd "$BACKEND_ROOT"
nohup "$CONDA_EXE" run -n "$ENV_NAME" --no-capture-output \
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > "$ROOT_DIR/logs/backend_stdout.log" 2> "$ROOT_DIR/logs/backend_stderr.log" &

echo "Backend: started PID=$! port 8000"
exit 0
