cd ~/redaction-deploy || exit 1
PY=~/anaconda3/envs/dataInfra/bin/python
LOG=~/models-dl.log
exec >> "$LOG" 2>&1
echo "=== LA RESUME $(date) ==="
"$PY" - <<'PY'
from modelscope import snapshot_download
kw = dict(model_id="nv-community/LocateAnything-3B",
          local_dir="backend/models/locateanything/LocateAnything-3B-HF")
try:
    p = snapshot_download(**kw, ignore_patterns=["assets/*","*.mp4","*.png","*.gif"])
except TypeError:
    p = snapshot_download(**kw, ignore_file_pattern=[r"assets/.*", r".*\.mp4", r".*\.png", r".*\.gif"])
print("LA_DONE", p)
PY
echo "=== LA DONE $(date) ==="
du -sh backend/models/locateanything/LocateAnything-3B-HF
ls backend/models/locateanything/LocateAnything-3B-HF/*.safetensors 2>/dev/null
