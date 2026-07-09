#!/bin/bash
cd ~/redaction-deploy || exit 1
LOG=~/deploy-bootstrap.log
exec >> "$LOG" 2>&1
echo "=== START $(date) ==="
echo "=== [1/4] pull vllm image ==="
docker pull vllm/vllm-openai:v0.19.1 && echo "VLLM_IMAGE_OK" || echo "VLLM_IMAGE_FAIL"
echo "=== [2/4] install huggingface_hub ==="
python3 -m pip install -q --break-system-packages 'huggingface_hub>=0.25' && echo "HF_HUB_OK" || echo "HF_HUB_FAIL"
mkdir -p backend/models/has backend/models/locateanything
echo "=== [3/4] download HaS_Text_0209_0.6B (bf16) ==="
python3 - <<'PY'
from huggingface_hub import snapshot_download
p = snapshot_download("xuanwulab/HaS_Text_0209_0.6B",
                      local_dir="backend/models/has/HaS_Text_0209_0.6B",
                      ignore_patterns=["*.gguf","*.onnx"])
print("HAS_DONE", p)
PY
echo "=== [4/4] download nvidia/LocateAnything-3B ==="
python3 - <<'PY'
from huggingface_hub import snapshot_download
try:
    p = snapshot_download("nvidia/LocateAnything-3B",
                          local_dir="backend/models/locateanything/LocateAnything-3B-HF")
    print("LA_DONE", p)
except Exception as e:
    print("LA_FAIL", type(e).__name__, str(e)[:300])
PY
echo "=== ALL DONE $(date) ==="
