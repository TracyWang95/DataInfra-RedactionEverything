cd ~/redaction-deploy/backend || exit 1
export PYTHONPATH=~/redaction-deploy/backend
export HAS_TEXT_RUNTIME=vllm
export HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:9080/v1
export HAS_TEXT_MODEL_NAME=HaS_Text_0209_0.6B
export OCR_BASE_URL=http://127.0.0.1:9082
export VISUAL_FEATURES_BASE_URL=http://127.0.0.1:9090
export VISUAL_SINGLE_CALL=1
export VISUAL_TILE_RETRY=0
export HAS_IMAGE_URL=http://127.0.0.1:9140
export ABSORB_SIGNATURES_IN_SEALS=0
export VISUAL_FEATURES_MODEL_NAME=GLM-4.6V-Flash-FP8
export LOCATE_ANYTHING_ENABLED=1
export OCR_STRUCTURE_ENABLED=true OCR_STRUCTURE_PRIMARY=true OCR_VL_ENABLED=1 VISION_DUAL_PIPELINE_PARALLEL=0 OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL=1 OCR_MAX_NEW_TOKENS=8192
export AUTH_ENABLED=true
export JWT_SECRET_KEY=REPLACE_WITH_YOUR_JWT_SECRET
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
