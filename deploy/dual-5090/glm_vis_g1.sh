cd ~/redaction-deploy/backend/scripts || exit 1
export GLM_BASE_URL=http://127.0.0.1:8121/v1
export GLM_MODEL_NAME=glm-fp8
export GLM_VISUAL_PORT=8131
exec /home/adminroot/anaconda3/envs/dataInfra/bin/python glm_visual_server.py
