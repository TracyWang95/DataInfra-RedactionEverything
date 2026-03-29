#!/usr/bin/env bash
set -euo pipefail

PORTS=(8080 8081 8082 8000 3000)

echo ""
echo "=== Legal Redaction - Stopping services on ports ${PORTS[*]} ==="
echo ""

for port in "${PORTS[@]}"; do
    # Find PIDs listening on this port
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [[ -z "$pids" ]]; then
        echo "Port $port : (no listener)"
        continue
    fi
    for pid in $pids; do
        if [[ "$pid" -eq 0 ]] 2>/dev/null; then continue; fi
        proc_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        echo "Port $port : stop PID $pid ($proc_name)"
        kill -9 "$pid" 2>/dev/null || echo "Port $port : could not stop PID $pid"
    done
done

sleep 2
echo ""
echo "Done."
echo ""
