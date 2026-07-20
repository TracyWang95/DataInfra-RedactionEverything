cd /data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend || exit 1
export PYTHONPATH=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend
export HAS_TEXT_RUNTIME=vllm
export HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:29080/v1
export HAS_TEXT_MODEL_NAME=HaS_Text_0209_0.6B
export OCR_BASE_URL=http://127.0.0.1:29082
export VISUAL_FEATURES_BASE_URL=http://127.0.0.1:29090
export VISUAL_TILE_RETRY=1
# Optional YOLO path; leave empty when has_image weights are not deployed.
export HAS_IMAGE_URL="${HAS_IMAGE_URL:-}"
export ABSORB_SIGNATURES_IN_SEALS=1
export VISUAL_FEATURES_MODEL_NAME=LocateAnything-3B
export LOCATE_ANYTHING_ENABLED=1
export AUTH_ENABLED=true
# JWT secret externalized to ~/.redaction_secrets (chmod 600) — CP0-5/CP5-1.
# Fail fast if the secrets file is missing rather than silently using a weak default.
if [ ! -f ~/.redaction_secrets ]; then echo 'FATAL: ~/.redaction_secrets missing'; exit 1; fi
. ~/.redaction_secrets
export JOB_CONCURRENCY=6
export BATCH_RECOGNITION_PAGE_CONCURRENCY=3
export DATA_DIR=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/data
export UPLOAD_DIR=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/uploads
export OUTPUT_DIR=/data/ubuntu/lh/projects/DataInfra-RedactionEverything/backend/outputs
mkdir -p "$DATA_DIR" "$UPLOAD_DIR" "$OUTPUT_DIR"
export HAS_NER_GLOBAL_MAX_INFLIGHT=6
export BATCH_VISUAL_MERGE_PAGE_CONCURRENCY=2
export GPU_SATURATION_RATIO=0.95
export LOCATE_ANYTHING_CONSENSUS_SAMPLES=1
export LOCATE_ANYTHING_CONSENSUS_MIN_VOTES=1
export VISUAL_DETECT_BATCH_CATEGORIES=true
export VISION_DUAL_PIPELINE_PARALLEL=false
export HAS_IMAGE_URL="http://127.0.0.1:29140"
export VISUAL_EDGE_SEAL_REFINE=0
export VISION_DETECTOR_EPOCH=2
exec /home/ubuntu/miniconda3/envs/dataInfra/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 28001 --workers 1
