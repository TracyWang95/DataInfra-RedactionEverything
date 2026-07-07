cd ~ && export LB_UPSTREAMS="http://127.0.0.1:8082,http://127.0.0.1:8083,http://127.0.0.1:8084,http://127.0.0.1:8085"
exec /home/adminroot/anaconda3/envs/dataInfra/bin/python -m uvicorn lb_proxy:app --host 0.0.0.0 --port 9082 --no-access-log
