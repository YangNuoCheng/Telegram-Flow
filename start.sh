#!/bin/sh
# 启动或重建服务（macOS / Linux）。输出含访问口令，请勿转发。
set -eu
cd "$(dirname "$0")"
if [ -z "${TG_FEED_LAN_IP:-}" ]; then
    if command -v ipconfig >/dev/null 2>&1; then          # macOS
        for iface in en0 en1; do
            TG_FEED_LAN_IP=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
            [ -z "$TG_FEED_LAN_IP" ] || break
        done
    elif command -v ip >/dev/null 2>&1; then              # Linux
        TG_FEED_LAN_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1)
    fi
    export TG_FEED_LAN_IP
fi
mkdir -p data
chmod 700 data
docker compose up -d --build --wait --wait-timeout 90
key=$(tr -d '[:space:]' < data/access_token)
echo "电脑访问：http://127.0.0.1:8978/?k=$key"
if [ -n "${TG_FEED_LAN_IP:-}" ]; then
    echo "手机 / 平板（同一 Wi-Fi）：http://$TG_FEED_LAN_IP:8978/?k=$key"
fi
echo "以上链接包含访问口令，请勿转发。停止：./stop.sh"
