cd ~/redaction-deploy/backend || exit 1
export PYTHONPATH=~/redaction-deploy/backend
export HAS_TEXT_RUNTIME=vllm
export HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:9080/v1
export HAS_TEXT_MODEL_NAME=HaS_Text_0209_0.6B
export OCR_BASE_URL=http://127.0.0.1:9082
export VISUAL_FEATURES_BASE_URL=http://127.0.0.1:9090
export LOCATE_ANYTHING_ENABLED=1
export OCR_STRUCTURE_ENABLED=true OCR_STRUCTURE_PRIMARY=true OCR_VL_ENABLED=1 VISION_DUAL_PIPELINE_PARALLEL=0 OCR_STRUCTURE_PRIMARY_SUPPLEMENT_VL=1 OCR_MAX_NEW_TOKENS=8192
export AUTH_ENABLED=true
export JWT_SECRET_KEY=redaction-5090-dualgpu-2026-fixed-secret-key-please-keep
export JOB_CONCURRENCY=6
export BATCH_RECOGNITION_PAGE_CONCURRENCY=3
# HaS NER 全局并发闸门：双卡 vLLM 双实例 × 每实例 ~3（KV 预算内）
export HAS_NER_GLOBAL_MAX_INFLIGHT=6
# 视觉特征合并趟并发：LA 双实例（split 拓扑）正好每实例一页
export BATCH_VISUAL_MERGE_PAGE_CONCURRENCY=2
# 双卡静态驻留 ~80%（OCR 扩容后），0.90 会把健康负载误判为饱和
export GPU_SATURATION_RATIO=0.95
export DATA_DIR=~/redaction-deploy/backend/data
export UPLOAD_DIR=~/redaction-deploy/backend/uploads
export OUTPUT_DIR=~/redaction-deploy/backend/outputs
mkdir -p "$DATA_DIR" "$UPLOAD_DIR" "$OUTPUT_DIR"
exec ~/anaconda3/envs/dataInfra/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
