cd ~/redaction-deploy/backend || exit 1
export PYTHONPATH=~/redaction-deploy/backend
export HAS_TEXT_RUNTIME=vllm
export HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:9080/v1
export HAS_TEXT_MODEL_NAME=HaS_Text_0209_0.6B
export OCR_BASE_URL=http://127.0.0.1:9082
export VISUAL_FEATURES_BASE_URL=http://127.0.0.1:9090
# VISUAL_TILE_RETRY=1: LocateAnything loses small / faint / edge marks (thumbprints,
# handwritten signatures, binding-seal slivers) when the full page is downscaled to
# its input; the zero-recall tile retry re-runs the missed category on zoomed tiles.
# (Was 0 — a GLM-era leftover: GLM's full-frame recall was scale-immune. VISUAL_SINGLE_CALL,
# another GLM-only flag, is removed; LocateAnything always fans out per category.)
export VISUAL_TILE_RETRY=1
export HAS_IMAGE_URL=http://127.0.0.1:9140
export ABSORB_SIGNATURES_IN_SEALS=1
export VISUAL_FEATURES_MODEL_NAME=LocateAnything-3B
export LOCATE_ANYTHING_ENABLED=1
export OCR_STRUCTURE_ENABLED=true OCR_STRUCTURE_PRIMARY=true OCR_VL_ENABLED=1 VISION_DUAL_PIPELINE_PARALLEL=0 OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL=1 OCR_MAX_NEW_TOKENS=8192
export AUTH_ENABLED=true
# JWT secret externalized to ~/.redaction_secrets (chmod 600) — CP0-5/CP5-1.
# Fail fast if the secrets file is missing rather than silently using a weak default.
if [ ! -f ~/.redaction_secrets ]; then echo 'FATAL: ~/.redaction_secrets missing'; exit 1; fi
. ~/.redaction_secrets
export JOB_CONCURRENCY=6
export BATCH_RECOGNITION_PAGE_CONCURRENCY=3
export DATA_DIR=~/redaction-deploy/backend/data
export UPLOAD_DIR=~/redaction-deploy/backend/uploads
export OUTPUT_DIR=~/redaction-deploy/backend/outputs
mkdir -p "$DATA_DIR" "$UPLOAD_DIR" "$OUTPUT_DIR"
export HAS_NER_GLOBAL_MAX_INFLIGHT=6
export BATCH_VISUAL_MERGE_PAGE_CONCURRENCY=2
export GPU_SATURATION_RATIO=0.95
exec ~/anaconda3/envs/dataInfra/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
