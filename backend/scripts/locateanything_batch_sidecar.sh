#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/d/DataInfra-RedactionEverything"
VENV="/home/tracy/.cache/datainfra-redaction/.venv-vllm/bin/activate"
PORT="${LOCATEANYTHING_BATCH_PORT:-8095}"
HOST="${LOCATEANYTHING_BATCH_HOST:-127.0.0.1}"
MODEL="${LA3B_MODEL:-/mnt/d/has_models/LocateAnything-3B-HF}"
BATCH_SRC="${LOCATEANYTHING_BATCH_SRC:-/mnt/d/tmp/LocateAnything-3B-batch/src}"
LOG="$ROOT/logs/locateanything-batch-server.log"
PIDFILE="$ROOT/tmp/locateanything-batch-server.pid"

cd "$ROOT"
mkdir -p logs tmp

find_port_pids() {
  ss -ltnp 2>/dev/null | awk -v port=":$PORT" '
    index($0, port) {
      while (match($0, /pid=[0-9]+/)) {
        print substr($0, RSTART + 4, RLENGTH - 4)
        $0 = substr($0, RSTART + RLENGTH)
      }
    }
  ' | sort -u
}

stop_server() {
  if [[ -f "$PIDFILE" ]]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  fi
  for pid in $(find_port_pids); do
    kill "$pid" 2>/dev/null || true
  done
  pkill -f "backend/scripts/locateanything_batch_server.py" 2>/dev/null || true
  rm -f "$PIDFILE"
}

start_server() {
  stop_server
  : > "$LOG"
  setsid nohup bash -lc "
    source '$VENV'
    export PYTHONUNBUFFERED=1
    export PYTHONPATH='$BATCH_SRC'
    export LA3B_MODEL='$MODEL'
    export HF_HUB_OFFLINE=1
    export MTP_FLASH_PREFILL=0
    exec python backend/scripts/locateanything_batch_server.py \
      --host '$HOST' \
      --port '$PORT' \
      --batch-src '$BATCH_SRC' \
      --model '$MODEL'
  " > "$LOG" 2>&1 < /dev/null &
  pid="$!"
  echo "$pid" > "$PIDFILE"
  echo "started pid=$pid port=$PORT log=$LOG"
}

status_server() {
  if [[ -f "$PIDFILE" ]]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]]; then
      ps -p "$pid" -o pid,ppid,stat,etime,cmd 2>/dev/null || true
    fi
  fi
  ss -ltnp 2>/dev/null | grep ":$PORT" || true
}

case "${1:-start}" in
  start) start_server ;;
  stop) stop_server ;;
  restart) start_server ;;
  status) status_server ;;
  *) echo "usage: $0 {start|stop|restart|status}" >&2; exit 2 ;;
esac
