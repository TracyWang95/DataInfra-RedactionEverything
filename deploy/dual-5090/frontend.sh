cd ~/redaction-deploy/frontend
export PATH=~/anaconda3/envs/dataInfra/bin:$PATH
exec npm run dev -- --host 0.0.0.0 --port 3000 --force
