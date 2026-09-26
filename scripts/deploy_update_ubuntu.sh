#!/usr/bin/env bash
# Existing-host update only. Run from an uploaded release directory as ubuntu.
set -Eeuo pipefail
umask 077
release_dir="$(pwd -P)"
app_dir=/home/ubuntu/zhongan-app
web_dir=/var/www/zhongan-web
[[ "$release_dir" == /home/ubuntu/zhongan-releases/release-* ]]
test -d "$app_dir/.venv"
test -f "$release_dir/services/api/sql/011_conversations.sql"
test -f "$release_dir/apps/web/dist/index.html"
test -f "$release_dir/REVISION"
backup_dir="$(mktemp -d /home/ubuntu/zhongan-backup.XXXXXXXX)"
chmod 700 "$backup_dir"
printf 'BACKUP_DIRECTORY=%s\n' "$backup_dir"
tar --exclude=.venv --exclude=__pycache__ -czf "$backup_dir/app.tar.gz" -C "$app_dir" .
tar -czf "$backup_dir/web.tar.gz" -C "$web_dir" .
sudo tar -czf "$backup_dir/config.tar.gz" -C / \
    etc/systemd/system/zhongan-api.service \
    etc/systemd/system/zhongan-worker.service \
    etc/nginx/sites-available/zhongan-api
sudo chown ubuntu:ubuntu "$backup_dir/config.tar.gz"
chmod 600 "$backup_dir"/*.tar.gz
stopped=0
rollback() {
    local result=$?
    trap - ERR
    set +e
    if [[ "$stopped" == 1 ]]; then
        # Restore code/config without destroying newer files or rolling back data.
        tar -xzf "$backup_dir/app.tar.gz" -C "$app_dir"
        sudo tar -xzf "$backup_dir/web.tar.gz" -C "$web_dir"
        sudo tar -xzf "$backup_dir/config.tar.gz" -C /
        sudo systemctl daemon-reload
        sudo systemctl restart zhongan-api zhongan-worker
        sudo nginx -t && sudo systemctl reload nginx
    fi
    printf 'DEPLOY_FAILED backup=%s exit=%s\n' "$backup_dir" "$result" >&2
    exit "$result"
}
trap rollback ERR
sudo systemctl stop zhongan-api zhongan-worker
stopped=1
set -a
. /home/ubuntu/.config/zhongan/database.env
set +a
# The DSN stays in process environment; only its database name is passed to pg_dump.
database_name="$($app_dir/.venv/bin/python -c 'import os,psycopg; c=psycopg.connect(os.environ["ZHONGAN_DATABASE_URL"]); print(c.info.dbname); c.close()')"
sudo -u postgres pg_dump --format=custom --dbname="$database_name" > "$backup_dir/database.dump"
test -s "$backup_dir/database.dump"
pg_restore --list "$backup_dir/database.dump" > "$backup_dir/database-manifest.txt"
cp -a "$release_dir/services" "$app_dir/"
install -d -m 755 "$app_dir/scripts" "$app_dir/contracts" "$app_dir/docs/medical"
cp -a "$release_dir/scripts/." "$app_dir/scripts/"
cp -a "$release_dir/contracts/knowledge" "$app_dir/contracts/"
cp -a "$release_dir/docs/medical/knowledge" "$app_dir/docs/medical/"
cp "$release_dir/REVISION" "$app_dir/REVISION"
cd "$app_dir"
"$app_dir/.venv/bin/python" -m scripts.migrate_database
"$app_dir/.venv/bin/python" -m pip check
sudo install -m 644 "$release_dir/deploy/zhongan-api.service" /etc/systemd/system/zhongan-api.service
sudo install -m 644 "$release_dir/deploy/zhongan-worker.service" /etc/systemd/system/zhongan-worker.service
sudo install -m 644 "$release_dir/deploy/nginx-zhongan-api.conf" /etc/nginx/sites-available/zhongan-api
# Keep old hashed assets available to already-open browser sessions.
sudo cp -a "$release_dir/apps/web/dist/." "$web_dir/"
sudo find "$web_dir" -type d -exec chmod 755 {} +
sudo find "$web_dir" -type f -exec chmod 644 {} +
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl restart zhongan-api zhongan-worker
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8000/health > /dev/null; then break; fi
    [[ "$attempt" -lt 20 ]]
    sleep 1
done
sudo systemctl reload nginx
systemctl is-active zhongan-api zhongan-worker nginx
curl -fsS http://127.0.0.1/health
printf '\nDEPLOYED_REVISION=%s\n' "$(< "$app_dir/REVISION")"
trap - ERR
