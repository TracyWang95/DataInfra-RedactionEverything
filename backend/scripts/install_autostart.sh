#!/usr/bin/env bash
# 安装 systemd 用户服务，实现登录/开机后自动启动本地栈。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNIT_SRC="${BACKEND_DIR}/systemd/redaction-everything.service"
UNIT_DST="${HOME}/.config/systemd/user/redaction-everything.service"

chmod +x "${SCRIPT_DIR}/autostart_local.sh"
chmod +x "${SCRIPT_DIR}/restart_all_local.sh"
chmod +x "${SCRIPT_DIR}/stop_all_local.sh"

mkdir -p "${HOME}/.config/systemd/user"
cp "${UNIT_SRC}" "${UNIT_DST}"

systemctl --user daemon-reload
systemctl --user enable redaction-everything.service

if loginctl enable-linger "${USER}" 2>/dev/null; then
  echo "[install] 已启用 linger：未登录时也会在开机后启动用户服务"
else
  echo "[install] WARN: 无法启用 linger，服务可能仅在登录后自启" >&2
fi

echo ""
echo "======== 开机自启已配置 ========"
echo "  服务名:  redaction-everything.service (user)"
echo "  单元文件: ${UNIT_DST}"
echo "  立即启动: systemctl --user start redaction-everything.service"
echo "  查看状态: systemctl --user status redaction-everything.service"
echo "  查看日志: tail -f ${BACKEND_DIR}/logs/autostart.log"
echo "  取消自启: systemctl --user disable redaction-everything.service"
echo "================================"
