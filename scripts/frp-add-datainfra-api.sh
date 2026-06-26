#!/usr/bin/env bash
# 将 DataInfra API（本地 8090）映射到 FRP 远程端口 8081
set -euo pipefail

FRPC_TOML="/usr/local/frp/frpc.toml"
PROXY_NAME="datainfra-api-tcp"
LOCAL_PORT="${BACKEND_PORT:-8090}"
REMOTE_PORT="8081"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo bash $0"
  exit 1
fi

if grep -q "name = \"${PROXY_NAME}\"" "${FRPC_TOML}"; then
  echo "映射 ${PROXY_NAME} 已存在，跳过写入。"
else
  cat >> "${FRPC_TOML}" <<EOF

[[proxies]]
name = "${PROXY_NAME}"
type = "tcp"
localIP = "127.0.0.1"
localPort = ${LOCAL_PORT}
remotePort = ${REMOTE_PORT}
EOF
  echo "已添加映射: 127.0.0.1:${LOCAL_PORT} -> 远程 ${REMOTE_PORT}"
fi

systemctl restart frpc
sleep 2
if systemctl is-active --quiet frpc; then
  echo "frpc 重启成功"
  journalctl -u frpc.service --no-pager -n 5 | grep -E 'datainfra-api-tcp|start proxy success|login to server success' || true
else
  echo "frpc 重启后状态异常，请检查: systemctl status frpc"
  exit 1
fi
