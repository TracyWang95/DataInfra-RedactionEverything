#!/usr/bin/env bash
# Frontend dev server (Vite) — port 3000
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$ROOT_DIR/frontend"

cd "$FRONTEND_DIR"

if [[ ! -f "package.json" ]]; then
    echo "ERROR: frontend not found in $FRONTEND_DIR"
    exit 1
fi

exec npx vite --host 127.0.0.1 --port 3000
