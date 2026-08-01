#!/bin/bash
# 将 Docker Hub 国内加速器写入 /etc/docker/daemon.json 并重启 Docker。
# 用法：sudo bash scripts/configure_docker_mirror.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$REPO_ROOT/scripts/cn_mirrors.env"; set +a

export DOCKER_REGISTRY_MIRRORS="${DOCKER_REGISTRY_MIRRORS:-https://docker.m.daocloud.io,https://mirror.ccs.tencentyun.com,https://i1r362m9.mirror.aliyuncs.com}"
export DOCKER_DAEMON_JSON="${DOCKER_DAEMON_JSON:-/etc/docker/daemon.json}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行：sudo bash $0" >&2
  exit 1
fi

mkdir -p "$(dirname "$DOCKER_DAEMON_JSON")"
python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["DOCKER_DAEMON_JSON"])
wanted = [m.strip() for m in os.environ["DOCKER_REGISTRY_MIRRORS"].split(",") if m.strip()]
data = {}
if path.exists() and path.read_text(encoding="utf-8").strip():
    data = json.loads(path.read_text(encoding="utf-8"))

existing = list(data.get("registry-mirrors") or [])
# 按 wanted 顺序优先，再追加原有其它镜像
merged = []
seen = set()
for m in wanted + existing:
    if m not in seen:
        seen.add(m)
        merged.append(m)
data["registry-mirrors"] = merged
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {path}")
print(json.dumps(data, indent=2, ensure_ascii=False))
PY

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl restart docker
  echo "docker restarted"
else
  echo "未检测到 systemctl，请手动重启 Docker 使 $DOCKER_DAEMON_JSON 生效"
fi

docker info 2>/dev/null | grep -A20 -i 'Registry Mirrors' || true
echo "OK: registry-mirrors -> $DOCKER_REGISTRY_MIRRORS"
