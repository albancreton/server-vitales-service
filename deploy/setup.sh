#!/usr/bin/env bash
# One-time host setup. Run as root: sudo REPO_URL=... ./setup.sh
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/albancreton/server-vitales-service.git}"
REPO="${REPO:-/opt/server-stats}"

if [ ! -d "$REPO/.git" ]; then
    git clone "$REPO_URL" "$REPO"
fi
cd "$REPO"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

for unit in vitalsd.service vitalsd-update.service vitalsd-update.timer; do
    sed "s|@REPO@|$REPO|g" "deploy/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now vitalsd.service vitalsd-update.timer
sleep 2
curl -fsS http://127.0.0.1:9877/health && echo
systemctl status vitalsd --no-pager --lines=5
