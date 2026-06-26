#!/usr/bin/env bash
# 修改 datainfra-api-tcp 的 FRP 远程端口并重启 frpc
set -euo pipefail

FRPC_TOML="/usr/local/frp/frpc.toml"
PROXY_NAME="datainfra-api-tcp"
REMOTE_PORT="${REMOTE_PORT:-8081}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo 运行: sudo bash $0"
  exit 1
fi

if ! grep -q "name = \"${PROXY_NAME}\"" "${FRPC_TOML}"; then
  echo "未找到 ${PROXY_NAME}，请先运行 scripts/frp-add-datainfra-api.sh"
  exit 1
fi

sed -i "/name = \"${PROXY_NAME}\"/,/^\[\[proxies\]\]/ s/remotePort = [0-9]*/remotePort = ${REMOTE_PORT}/" "${FRPC_TOML}"
# 若 datainfra-api-tcp 是最后一个 proxy，上面可能未匹配到；再精确替换一次
sed -i "/name = \"${PROXY_NAME}\"/,/^$/ s/remotePort = [0-9]*/remotePort = ${REMOTE_PORT}/" "${FRPC_TOML}"

echo "已更新 ${PROXY_NAME} -> remotePort ${REMOTE_PORT}"
grep -A5 "name = \"${PROXY_NAME}\"" "${FRPC_TOML}"

systemctl restart frpc
sleep 2
if systemctl is-active --quiet frpc; then
  echo "frpc 重启成功"
  journalctl -u frpc.service --no-pager -n 10 | grep -E "${PROXY_NAME}|port unavailable|start proxy success" || true
else
  echo "frpc 重启后状态异常，请检查: systemctl status frpc"
  exit 1
fi
