#!/usr/bin/env bash
set -euo pipefail
release_dir="$(cd "$1" && pwd -P)"
[[ "$release_dir" == /home/ubuntu/zhongan-judge-releases/release-* ]]
app_dir=/home/ubuntu/zhongan-app
entry_dir=/home/ubuntu/zhongan-judge-demo
unit=/etc/systemd/system/zhongan-judge-demo.service
snippet=/etc/nginx/zhongan-judge-entry.conf
nginx_conf=/etc/nginx/sites-available/zhongan-api
install -d -m 700 "$release_dir/backup"
previous_entry="$(readlink "$entry_dir" || true)"
[[ ! -e "$entry_dir" || -L "$entry_dir" ]]
sudo cp -a "$nginx_conf" "$release_dir/backup/nginx.conf"
[[ ! -e "$unit" ]] || sudo cp -a "$unit" "$release_dir/backup/unit"
[[ ! -e "$snippet" ]] || sudo cp -a "$snippet" "$release_dir/backup/snippet"
changed=0
rollback() {
    result=$?
    trap - ERR
    if [[ "$changed" == 1 ]]; then
        sudo cp -a "$release_dir/backup/nginx.conf" "$nginx_conf"
        if [[ -e "$release_dir/backup/snippet" ]]; then
            sudo cp -a "$release_dir/backup/snippet" "$snippet"
        else
            sudo unlink "$snippet" || true
        fi
        if [[ -n "$previous_entry" ]]; then
            ln -s "$previous_entry" "$entry_dir.rollback"
            mv -Tf "$entry_dir.rollback" "$entry_dir"
        else
            sudo systemctl disable --now zhongan-judge-demo || true
            unlink "$entry_dir" || true
        fi
        if [[ -e "$release_dir/backup/unit" ]]; then
            sudo cp -a "$release_dir/backup/unit" "$unit"
        else
            sudo unlink "$unit" || true
        fi
        sudo systemctl daemon-reload
        if [[ -n "$previous_entry" ]]; then sudo systemctl restart zhongan-judge-demo; fi
        sudo nginx -t && sudo systemctl reload nginx
    fi
    exit "$result"
}
trap rollback ERR
set -a
. /home/ubuntu/.config/zhongan/database.env
set +a
export PYTHONPATH="$app_dir"
"$app_dir/.venv/bin/python" "$release_dir/services/judge_demo/prepare.py"
"$app_dir/.venv/bin/python" - "$nginx_conf" "$release_dir/nginx.conf" <<'PY'
import sys
from pathlib import Path
source=Path(sys.argv[1]).read_text()
include='    include /etc/nginx/zhongan-judge-entry*.conf;'
if include not in source:
    marker='server {'
    if source.count(marker)!=1:
        raise SystemExit('Refuse ambiguous Nginx server config')
    source=source.replace(marker, marker+'\n'+include, 1)
Path(sys.argv[2]).write_text(source)
PY
changed=1
ln -s "$release_dir" "$entry_dir.next"
mv -Tf "$entry_dir.next" "$entry_dir"
sudo install -m 644 "$release_dir/deploy/zhongan-judge-demo.service" "$unit"
sudo systemctl daemon-reload
sudo systemctl enable zhongan-judge-demo
sudo systemctl restart zhongan-judge-demo
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8010/judge/health > /dev/null; then break; fi
    [[ "$attempt" -lt 20 ]]
    sleep 1
done
sudo install -m 644 "$release_dir/deploy/nginx-zhongan-judge-entry.conf" "$snippet"
sudo install -m 644 "$release_dir/nginx.conf" "$nginx_conf"
sudo nginx -t
sudo systemctl reload nginx
# Reload returns before old workers exit; verify the actual proxy response.
for attempt in {1..10}; do
    if curl -fsS http://127.0.0.1/judge/health | "$app_dir/.venv/bin/python" -c 'import json,sys; value=json.load(sys.stdin); assert value=={"status":"ok","capacity":50}'; then break; fi
    [[ "$attempt" -lt 10 ]]
    sleep 1
done
systemctl is-active zhongan-judge-demo zhongan-api zhongan-worker nginx
trap - ERR
