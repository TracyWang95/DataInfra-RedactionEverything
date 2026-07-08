cd ~ && export LB_UPSTREAMS="http://127.0.0.1:8090,http://127.0.0.1:8091"
exec /home/adminroot/anaconda3/envs/dataInfra/bin/python -m uvicorn lb_proxy:app --host 0.0.0.0 --port 9090 --no-access-log
