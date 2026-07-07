#!/bin/bash
# One-command (re)start of the full RedactionEverything dual-5090 stack.
# Self-healing: only launches a service whose port is currently DOWN, so it is
# safe to run anytime (after a reboot, or to revive a crashed service).
# Reuses the proven per-service launch scripts -> identical memory-safe GPU config
# (vllm gpu-memory-utilization 0.22 x2 etc.), so it will NOT OOM the shared box.
set -u
mkdir -p ~/logs

up(){ ss -ltn 2>/dev/null | grep -q ":$1 "; }
launch(){ # name port script
  local name=$1 port=$2 script=$3
  if up "$port"; then echo "  [skip] $name :$port already UP"; return; fi
  if [ ! -f "$script" ]; then echo "  [MISS] $name: no $script"; return; fi
  nohup bash "$script" > ~/logs/"$name".log 2>&1 &
  echo "  [start] $name :$port (pid $!) -> ~/logs/$name.log"
}

echo "=== model services (GPU0 / GPU1) ==="
launch vl_serve_g0 8118 ~/vl_serve_g0.sh
launch vl_serve_g1 8119 ~/vl_serve_g1.sh
launch has_g0 8080 ~/has_g0.sh
launch has_g1 8081 ~/has_g1.sh
launch la_lm_g0 8092 ~/la_lm_g0.sh
launch la_lm_g1 8093 ~/la_lm_g1.sh
echo "  [wait] LA LM :8092 + :8093 ready before LA-vision ..."
for i in $(seq 1 60); do curl -sf -m3 localhost:8092/v1/models >/dev/null 2>&1 && curl -sf -m3 localhost:8093/v1/models >/dev/null 2>&1 && { echo "  [ok] :8092+:8093 ready"; break; }; sleep 3; done
launch la_g0  8090 ~/la_g0.sh
launch la_g1  8091 ~/la_g1.sh
# OCR warmup POSTs to the VL recognition server (:8118); wait until it is ready
# before launching OCR, otherwise ocr init warmup fails and the service exits.
echo "  [wait] VL servers :8118 + :8119 ready before OCR ..."
for i in $(seq 1 60); do curl -sf -m3 localhost:8118/v1/models >/dev/null 2>&1 && curl -sf -m3 localhost:8119/v1/models >/dev/null 2>&1 && { echo "  [ok] :8118+:8119 ready"; break; }; sleep 3; done
launch ocr_g0 8082 ~/ocr_g0.sh
launch ocr_g1 8083 ~/ocr_g1.sh
launch ocr_g0b 8084 ~/ocr_g0b.sh
launch ocr_g1b 8085 ~/ocr_g1b.sh

echo "=== load balancers (round-robin across GPU0/GPU1) ==="
launch lb_has 9080 ~/lb_has.sh
launch lb_ocr 9082 ~/lb_ocr.sh
launch lb_la  9090 ~/lb_la.sh

echo "=== backend (FastAPI :8000) ==="
launch backend 8000 ~/backend_g0.sh

echo "=== frontend (PRODUCTION preview, fast bundle -- NOT vite dev) ==="
if up 3000; then
  echo "  [skip] frontend :3000 already UP"
else
  ( cd ~/redaction-deploy/frontend \
    && export PATH=~/anaconda3/envs/dataInfra/bin:$PATH \
    && npx vite build >> ~/logs/frontend.log 2>&1 \
    && exec nohup npx vite preview --host 0.0.0.0 --port 3000 --strictPort >> ~/logs/frontend.log 2>&1 ) &
  echo "  [start] frontend build+preview -> ~/logs/frontend.log"
fi

echo ""
echo "Model services warm up over ~1-3 min (vllm + LocateAnything load weights)."
echo "Re-check status with:"
echo '  for p in 8118 8080 8081 8082 8083 8090 8091 9080 9082 9090 8000 3000; do ss -ltn|grep -q ":$p " && echo "  :$p UP" || echo "  :$p DOWN"; done'

