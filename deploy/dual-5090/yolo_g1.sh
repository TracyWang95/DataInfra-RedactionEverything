cd ~/redaction-deploy/backend/scripts || exit 1
export CUDA_VISIBLE_DEVICES=1
export HAS_IMAGE_PORT=8141
exec /home/adminroot/rvenv/la/bin/python has_image_server.py
