#!/bin/bash
# Enable FRP mapping 127.0.0.1:8501 -> frpserver:18501 and restart the root frpc.
# Needs sudo because /home/guo/app/frp/frpc is started by systemd as root.
set -euo pipefail
CONF=/home/guo/app/frp/frpc.toml
if ! grep -q 'name = "greenpower-web"' "$CONF"; then
  printf '\n[[proxies]]\nname = "greenpower-web"\ntype = "tcp"\nlocalIP = "127.0.0.1"\nlocalPort = 8501\nremotePort = 18501\n' >> "$CONF"
  echo "appended greenpower-web proxy to $CONF"
else
  echo "greenpower-web proxy already present"
fi
sudo systemctl restart frpc.service
sudo systemctl --no-pager --full status frpc.service | head -20
echo "Access: http://47.116.1.6:18501"
