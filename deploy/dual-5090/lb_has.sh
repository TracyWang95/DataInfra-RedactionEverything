cd ~ && export LB_UPSTREAMS="http://127.0.0.1:8080,http://127.0.0.1:8081"
exec /home/adminroot/anaconda3/envs/dataInfra/bin/python -m uvicorn lb_proxy:app --host 0.0.0.0 --port 9080 --no-access-log
