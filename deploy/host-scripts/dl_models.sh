#!/bin/bash
cd ~/redaction-deploy || exit 1
LOG=~/models-dl.log
PY=~/anaconda3/envs/dataInfra/bin/python
exec >> "$LOG" 2>&1
echo "=== START $(date) ==="
"$PY" -m pip install -q huggingface_hub 2>&1 | tail -1
mkdir -p backend/models/has backend/models/locateanything
echo "=== [1/2] HaS_Text_0209_0.6B (bf16) ==="
"$PY" - <<'PY'
from huggingface_hub import snapshot_download
try:
    p = snapshot_download("xuanwulab/HaS_Text_0209_0.6B",
                          local_dir="backend/models/has/HaS_Text_0209_0.6B",
                          ignore_patterns=["*.gguf","*.onnx","*.Q4*","*.Q8*"])
    print("HAS_DONE", p)
except Exception as e:
    print("HAS_FAIL", type(e).__name__, str(e)[:300])
PY
echo "=== [2/2] nvidia/LocateAnything-3B ==="
"$PY" - <<'PY'
from huggingface_hub import snapshot_download
try:
    p = snapshot_download("nvidia/LocateAnything-3B",
                          local_dir="backend/models/locateanything/LocateAnything-3B-HF")
    print("LA_DONE", p)
except Exception as e:
    print("LA_FAIL", type(e).__name__, str(e)[:400])
PY
echo "=== ALL DONE $(date) ==="
du -sh backend/models/has/* backend/models/locateanything/* 2>/dev/null
