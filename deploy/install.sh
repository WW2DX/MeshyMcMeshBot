#!/usr/bin/env bash
# Run on the Pi from the repo checkout:  sudo ./deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

apt-get install -y python3-venv rsync
id meshbot &>/dev/null || useradd --system --home /opt/meshbot --shell /usr/sbin/nologin meshbot
usermod -aG dialout meshbot

mkdir -p /opt/meshbot /etc/meshbot
rsync -a --delete --exclude venv --exclude .git ./ /opt/meshbot/
python3 -m venv /opt/meshbot/venv
/opt/meshbot/venv/bin/pip install -q -r /opt/meshbot/requirements.txt

if [ ! -f /etc/meshbot/config.yaml ]; then
  cp config.example.yaml /etc/meshbot/config.yaml
  echo ">> Edit /etc/meshbot/config.yaml, then: sudo systemctl restart meshbot"
fi
chown -R meshbot:meshbot /opt/meshbot
chown root:meshbot /etc/meshbot/config.yaml && chmod 640 /etc/meshbot/config.yaml

cp deploy/99-meshbot.rules /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger

cp deploy/meshbot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now meshbot
echo ">> Logs: journalctl -u meshbot -f"
