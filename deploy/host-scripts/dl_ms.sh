#!/bin/bash
cd ~/redaction-deploy || exit 1
LOG=~/models-dl.log
PY=~/anaconda3/envs/dataInfra/bin/python
exec >> "$LOG" 2>&1
echo "=== MODELSCOPE DL START $(date) ==="
mkdir -p backend/models/has backend/models/locateanything
echo "=== [1/2] HaS_Text_0209_0.6B (TencentXuanwu) ==="
"$PY" - <<'PY'
from modelscope import snapshot_download
try:
    p = snapshot_download("TencentXuanwu/HaS_Text_0209_0.6B",
                          local_dir="backend/models/has/HaS_Text_0209_0.6B")
    print("HAS_DONE", p)
except Exception as e:
    print("HAS_FAIL", type(e).__name__, str(e)[:300])
PY
echo "=== [2/2] LocateAnything-3B (nv-community, skip demos) ==="
"$PY" - <<'PY'
from modelscope import snapshot_download
kw = dict(model_id="nv-community/LocateAnything-3B",
          local_dir="backend/models/locateanything/LocateAnything-3B-HF")
try:
    p = snapshot_download(**kw, ignore_patterns=["assets/*","*.mp4","*.png","*.gif"])
except TypeError:
    try:
        p = snapshot_download(**kw, ignore_file_pattern=[r"assets/.*", r".*\.mp4", r".*\.png", r".*\.gif"])
    except Exception as e:
        print("LA_FAIL_FILTER", str(e)[:200]); p = snapshot_download(**kw)
print("LA_DONE", p)
PY
echo "=== ALL DONE $(date) ==="
du -sh backend/models/has/HaS_Text_0209_0.6B backend/models/locateanything/LocateAnything-3B-HF 2>/dev/null
