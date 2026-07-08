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
# 2026-07-08 ROLLBACK to LocateAnything-primary: GLM-4.6V mis-boxed seals on
# real photographed legal docs (报警回执: seal box shifted onto body text),
# while LA localizes them tight. GLM won the 25-image GT set (25/25 vs 19/25)
# but that set over-fit; real 法律文书 favor LA. GLM stack disabled; re-enable
# glm_fp8_* + glm_vis_* and point lb_la back to 8130/8131 to revert.
#launch glm_fp8_g0 8120 ~/glm_fp8_g0.sh
#launch glm_fp8_g1 8121 ~/glm_fp8_g1.sh
#launch glm_vis_g0 8130 ~/glm_vis_g0.sh
#launch glm_vis_g1 8131 ~/glm_vis_g1.sh
launch yolo_g0 8140 ~/yolo_g0.sh
launch yolo_g1 8141 ~/yolo_g1.sh
# Dual LocateAnything-3B (pure HF, 1280px, no vLLM sidecar). lb_la -> 8090,8091.
launch la_g0 8090 ~/la_g0.sh
launch la_g1 8091 ~/la_g1.sh
# OCR warmup POSTs to the VL recognition server (:8118); wait until it is ready
# before launching OCR, otherwise ocr init warmup fails and the service exits.
echo "  [wait] VL servers :8118 + :8119 ready before OCR ..."
for i in $(seq 1 60); do curl -sf -m3 localhost:8118/v1/models >/dev/null 2>&1 && curl -sf -m3 localhost:8119/v1/models >/dev/null 2>&1 && { echo "  [ok] :8118+:8119 ready"; break; }; sleep 3; done
launch ocr_g0 8082 ~/ocr_g0.sh
#OCRg0only launch ocr_g1 8083 ~/ocr_g1.sh
launch ocr_g0b 8084 ~/ocr_g0b.sh
#OCRg0only launch ocr_g1b 8085 ~/ocr_g1b.sh

echo "=== load balancers (round-robin across GPU0/GPU1) ==="
launch lb_has 9080 ~/lb_has.sh
launch lb_ocr 9082 ~/lb_ocr.sh
launch lb_la  9090 ~/lb_la.sh
launch lb_yolo 9140 ~/lb_yolo.sh

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

