#!/usr/bin/env bash
# HaS NER (llama.cpp) — port 8080
# If conda env has llama-server, use conda run; otherwise fall back to PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_OUT="$LOG_DIR/has_llama_stdout.log"
LOG_ERR="$LOG_DIR/has_llama_stderr.log"

ENV_NAME="${LEGAL_REDACTION_CONDA_ENV:-legal-redaction}"

# --- Locate conda ---
find_conda_root() {
    if [[ -n "${CONDA_ROOT:-}" && -x "$CONDA_ROOT/bin/conda" ]]; then
        echo "$CONDA_ROOT"; return
    fi
    # Check common locations
    for c in "$HOME/anaconda3" "$HOME/miniconda3" "/opt/conda" "/opt/anaconda3" "/opt/miniconda3"; do
        if [[ -x "$c/bin/conda" ]]; then echo "$c"; return; fi
    done
    # Try which
    local cmd
    cmd=$(command -v conda 2>/dev/null || true)
    if [[ -n "$cmd" ]]; then
        # conda binary -> conda_root/bin/conda or conda_root/condabin/conda
        echo "$(dirname "$(dirname "$cmd")")"; return
    fi
    echo ""
}

CONDA_ROOT_DIR=$(find_conda_root)
CONDA_EXE="${CONDA_ROOT_DIR:+$CONDA_ROOT_DIR/bin/conda}"

# --- Locate llama-server inside conda env ---
LLAMA_CONDA=""
if [[ -n "$CONDA_ROOT_DIR" ]]; then
    for rel in "envs/$ENV_NAME/bin/llama-server" "envs/$ENV_NAME/Library/bin/llama-server"; do
        p="$CONDA_ROOT_DIR/$rel"
        if [[ -x "$p" ]]; then LLAMA_CONDA="$p"; break; fi
    done
fi

# --- Locate llama-server on PATH ---
LLAMA_PATH=$(command -v llama-server 2>/dev/null || true)

LLAMA_SERVER="${LLAMA_CONDA:-$LLAMA_PATH}"
if [[ -z "$LLAMA_SERVER" ]]; then
    msg="llama-server not found. Install in conda env $ENV_NAME or add to PATH."
    echo "[ERR] $msg"
    echo "$msg" > "$LOG_DIR/has_start_failed.txt"
    exit 1
fi

# --- Resolve model file ---
HF_REPO="${HAS_NER_HF_REPO:-xuanwulab/HaS_Text_0209_0.6B_Q4}"
WORKSPACE_ROOT="$(dirname "$ROOT_DIR")"

HAS_MODELS_DIR=""
if [[ -n "${HAS_MODELS_DIR_ENV:-${HAS_MODELS_DIR:-}}" && -d "${HAS_MODELS_DIR_ENV:-${HAS_MODELS_DIR:-}}" ]]; then
    HAS_MODELS_DIR="${HAS_MODELS_DIR_ENV:-${HAS_MODELS_DIR:-}}"
elif [[ -d "/data/has_models" ]]; then
    HAS_MODELS_DIR="/data/has_models"
else
    HAS_MODELS_DIR="$WORKSPACE_ROOT/has_models"
fi

DEFAULT_GGUF="$HAS_MODELS_DIR/HaS_Text_0209_0.6B_Q4_K_M.gguf"
LEGACY_GGUF="$HAS_MODELS_DIR/has_4.0_0.6B_q4.gguf"

HAS_MODEL=""
if [[ -n "${HAS_NER_GGUF:-}" && -f "${HAS_NER_GGUF}" ]]; then
    HAS_MODEL="$HAS_NER_GGUF"
elif [[ -f "$DEFAULT_GGUF" ]]; then
    HAS_MODEL="$DEFAULT_GGUF"
elif [[ -f "$LEGACY_GGUF" ]]; then
    HAS_MODEL="$LEGACY_GGUF"
    echo "HaS NER: using legacy GGUF $HAS_MODEL (set HAS_NER_GGUF to HaS_Text_0209 .gguf for latest)"
fi

NGL="${HAS_NER_NGL:-99}"

if [[ -n "$HAS_MODEL" ]]; then
    echo "HaS NER: local model $HAS_MODEL"
    LLAMA_ARGS=(-m "$HAS_MODEL" --port 8080 -ngl "$NGL" --host 0.0.0.0 -c 8192 -np 1)
else
    echo "HaS NER: no local .gguf, using -hf $HF_REPO"
    LLAMA_ARGS=(-hf "$HF_REPO" --port 8080 -ngl "$NGL" --host 0.0.0.0 -c 8192 -np 1)
fi

echo "HaS NER: llama-server = $LLAMA_SERVER"
if [[ -n "$LLAMA_CONDA" ]]; then
    echo "HaS NER: using conda env $ENV_NAME"
else
    echo "HaS NER: using system llama-server"
fi
echo "HaS NER: logs -> $LOG_OUT | $LOG_ERR"

> "$LOG_OUT"
> "$LOG_ERR"

if [[ -n "$LLAMA_CONDA" && -n "$CONDA_EXE" && -x "$CONDA_EXE" ]]; then
    nohup "$CONDA_EXE" run -n "$ENV_NAME" --no-capture-output \
        "$LLAMA_SERVER" "${LLAMA_ARGS[@]}" \
        > "$LOG_OUT" 2> "$LOG_ERR" &
    echo "HaS NER: started PID=$! port 8080 (conda run)"
else
    nohup "$LLAMA_SERVER" "${LLAMA_ARGS[@]}" \
        > "$LOG_OUT" 2> "$LOG_ERR" &
    echo "HaS NER: started PID=$! port 8080"
fi

exit 0
