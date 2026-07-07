cd ~/redaction-deploy/backend || exit 1
export CUDA_VISIBLE_DEVICES=0
export PYTHONPATH=~/redaction-deploy/backend
export OCR_VL_ENABLED=0
export OCR_STRUCTURE_ENABLED=true
export OCR_STRUCTURE_PRIMARY=true
export OCR_STRUCTURE_WARMUP=1
export OCR_MAX_IMAGE_SIDE=2048
export OCR_PORT=8082
export PADDLE_PDX_MODEL_SOURCE=modelscope
exec ~/anaconda3/envs/dataInfra/bin/python scripts/ocr_server.py
