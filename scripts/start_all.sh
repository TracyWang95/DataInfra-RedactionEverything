#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Stop existing services first
STOP_SCRIPT="$SCRIPT_DIR/stop_all.sh"
if [[ -x "$STOP_SCRIPT" ]]; then
    echo "Stopping existing services..."
    "$STOP_SCRIPT" || true
fi

echo ""
echo "=== Legal Redaction - Starting all services ==="
echo ""

# Start HaS NER (8080)
echo "Start HaS NER (8080)..."
"$SCRIPT_DIR/start_has.sh" &

# Start HaS Image YOLO (8081)
echo "Start HaS Image (8081)..."
"$SCRIPT_DIR/start_has_image.sh" &

# Start PaddleOCR-VL (8082) — skip if script not present
if [[ -x "$SCRIPT_DIR/start_paddle_ocr.sh" ]]; then
    echo "Start PaddleOCR-VL (8082)..."
    "$SCRIPT_DIR/start_paddle_ocr.sh" &
fi

# Start Backend (8000)
echo "Start Backend (8000)..."
"$SCRIPT_DIR/start_backend.sh" &

# Wait for backend to initialize
echo "Waiting for backend (uvicorn + conda may need 15-30s)..."
sleep 20

# Start Frontend (3000)
echo "Start Frontend dev / HMR (3000)..."
"$SCRIPT_DIR/start_frontend.sh" &

echo ""
echo "Done! Frontend dev (HMR): http://localhost:3000/"
echo "API docs: http://localhost:8000/docs"
echo ""
echo "All services started. Use stop_all.sh to stop."
wait
