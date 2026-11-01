#!/usr/bin/env bash
# Run on the Pi from the repo checkout:  sudo ./deploy/install.sh
# Safe to re-run to update; settings made over the mesh are kept.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA=/var/lib/meshbot

apt-get install -y python3-venv rsync
id meshbot &>/dev/null || useradd --system --home /opt/meshbot --shell /usr/sbin/nologin meshbot
usermod -aG dialout meshbot

mkdir -p /opt/meshbot
rsync -a --delete --exclude venv --exclude .git ./ /opt/meshbot/
python3 -m venv /opt/meshbot/venv
/opt/meshbot/venv/bin/pip install -q -r /opt/meshbot/requirements.txt
chown -R meshbot:meshbot /opt/meshbot

cp deploy/99-meshbot.rules /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger

cp deploy/meshbot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable meshbot
systemctl restart meshbot

echo ">> Bot is running. Logs: journalctl -u meshbot -f"

# An unclaimed bot writes a one-time setup code at startup.
for _ in $(seq 30); do
  [ -f "$DATA/setup-code.txt" ] && break
  sleep 1
done
if [ -f "$DATA/setup-code.txt" ]; then
  CODE=$(tr -dc 0-9 < "$DATA/setup-code.txt")
  echo
  echo ">> Setup code: ${CODE:0:3}-${CODE:3:3}"
  echo ">> 1. From your phone, send an advert so the bot learns your node."
  echo ">> 2. When the bot appears in your contacts, DM it:  claim $CODE"
  echo ">> 3. Then DM it:  zip <your ZIP code>"
  echo ">> (Lost it? sudo cat $DATA/setup-code.txt)"
else
  echo ">> Already claimed. Configure it over the mesh (DM the bot 'setup')."
fi
