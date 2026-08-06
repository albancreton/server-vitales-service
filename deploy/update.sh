#!/usr/bin/env bash
# Pull latest main, reinstall deps, restart vitalsd; roll back if /health fails.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

git fetch origin main
old=$(git rev-parse HEAD)
new=$(git rev-parse origin/main)
if [ "$old" = "$new" ]; then
    echo "vitalsd up to date ($old)"
    exit 0
fi

apply() {
    git reset --hard "$1"
    .venv/bin/pip install -q -r requirements.txt
    # Re-render units so changes to deploy/* actually reach systemd.
    for unit in vitalsd.service vitalsd-update.service vitalsd-update.timer; do
        sed "s|@REPO@|$REPO|g" "deploy/$unit" > "/etc/systemd/system/$unit"
    done
    systemctl daemon-reload
    systemctl restart vitalsd
}

health() {
    for _ in 1 2 3 4 5; do
        sleep 3
        if curl -fsS -m 2 http://127.0.0.1:9877/health >/dev/null; then
            return 0
        fi
    done
    return 1
}

echo "updating $old -> $new"
# apply in an if-context so a mid-apply failure (pip, systemctl) still
# reaches the rollback branch instead of aborting under set -e.
if ! apply "$new" || ! health; then
    echo "update failed, rolling back to $old" >&2
    apply "$old" || true
    exit 1
fi
echo "update ok ($new)"
