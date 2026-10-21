#!/usr/bin/env bash
# Existing-host update only. Run from an uploaded release directory as ubuntu.
set -Eeuo pipefail
umask 077
release_dir="$(pwd -P)"
app_dir=/home/ubuntu/zhongan-app
web_dir=/var/www/zhongan-web
judge_dir=/home/ubuntu/zhongan-judge-demo/services/judge_demo
[[ "$release_dir" == /home/ubuntu/zhongan-releases/release-* ]]
exec 9>/home/ubuntu/zhongan-releases/deploy.lock
flock -n 9 || { echo 'Another deployment is already running' >&2; exit 1; }
test -d "$app_dir/.venv"
test -f "$release_dir/services/api/sql/011_conversations.sql"
test -f "$release_dir/apps/web/dist/index.html"
test -f "$release_dir/REVISION"
test -x "$release_dir/output_dir/memory-ranker/semantix-ranker"
printf '%s\n' '{"protocol":"zhongan-memory-rank-v1","request_id":"deploy-probe","query":"","documents":[]}' | "$release_dir/output_dir/memory-ranker/semantix-ranker" | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r["protocol"]=="zhongan-memory-rank-v1" and r["request_id"]=="deploy-probe" and r["hits"]==[]'
revision="$(< "$release_dir/REVISION")"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
mobile_dir="$release_dir/output_dir/mobile-demo/dist"
test -f "$mobile_dir/index.html"
test "$(< "$mobile_dir/CI_REVISION")" = "$revision"
test "$(< "$release_dir/apps/web/dist/CI_REVISION")" = "$revision"
previous_mobile=''
if [[ -L "$web_dir/mobile-demo" ]]; then
    previous_mobile="$(readlink "$web_dir/mobile-demo")"
elif [[ -e "$web_dir/mobile-demo" ]]; then
    echo 'Existing mobile-demo must be a release symlink' >&2; exit 1
fi
mobile_switched=0
backup_dir="$(mktemp -d /home/ubuntu/zhongan-backup.XXXXXXXX)"
chmod 700 "$backup_dir"
printf 'BACKUP_DIRECTORY=%s\n' "$backup_dir"
tar --exclude=.venv --exclude=__pycache__ -czf "$backup_dir/app.tar.gz" -C "$app_dir" .
judge_changed=0
if [[ -d "$judge_dir" ]]; then
    tar --exclude=__pycache__ -czf "$backup_dir/judge.tar.gz" -C "$judge_dir" .
    for file in app.py entry.js index.html prepare.py; do
        if ! cmp -s "$release_dir/services/judge_demo/$file" "$judge_dir/$file"; then judge_changed=1; fi
    done
fi
tar -czf "$backup_dir/web.tar.gz" -C "$web_dir" .
sudo tar -czf "$backup_dir/config.tar.gz" -C / \
    etc/systemd/system/zhongan-api.service \
    etc/systemd/system/zhongan-worker.service \
    etc/nginx/sites-available/zhongan-api
sudo chown ubuntu:ubuntu "$backup_dir/config.tar.gz"
chmod 600 "$backup_dir"/*.tar.gz
backend_changed=0
# UI releases keep the API/worker running. Compare all runtime code, schemas,
# knowledge and service definitions; uncertainty takes the full backup path.
for relative in services contracts/knowledge contracts/medical-services docs/medical/knowledge; do
    if ! diff -qr --exclude=__pycache__ "$release_dir/$relative" "$app_dir/$relative" >/dev/null; then
        backend_changed=1
    fi
done
if [[ -d "$release_dir/skills" || -d "$app_dir/skills" ]]; then
    if ! diff -qr "$release_dir/skills" "$app_dir/skills" >/dev/null; then backend_changed=1; fi
fi
for unit in zhongan-api zhongan-worker; do
    if ! cmp -s "$release_dir/deploy/$unit.service" "/etc/systemd/system/$unit.service"; then
        backend_changed=1
    fi
done
if ! cmp -s "$release_dir/output_dir/memory-ranker/semantix-ranker" "$app_dir/output_dir/memory-ranker/semantix-ranker"; then
    backend_changed=1
fi
printf 'BACKEND_CHANGED=%s\n' "$backend_changed"
stopped=0
changed=0
rollback() {
    local result=$?
    trap - ERR
    set +e
    if [[ "$changed" == 1 || "$stopped" == 1 ]]; then
        # Restore code/config without destroying newer files or rolling back data.
        if [[ "$stopped" == 1 ]]; then
            tar -xzf "$backup_dir/app.tar.gz" -C "$app_dir"
        else
            tar -xzf "$backup_dir/app.tar.gz" -C "$app_dir" ./scripts ./REVISION
        fi
        sudo tar -xzf "$backup_dir/web.tar.gz" -C "$web_dir"
        if [[ "$mobile_switched" == 1 ]]; then
            if [[ -n "$previous_mobile" ]]; then
                sudo ln -s "$previous_mobile" "$web_dir/.mobile-demo-rollback-$revision"
                sudo mv -Tf "$web_dir/.mobile-demo-rollback-$revision" "$web_dir/mobile-demo"
            elif [[ "$(readlink "$web_dir/mobile-demo")" == ".mobile-demo-releases/$revision" ]]; then
                sudo unlink "$web_dir/mobile-demo"
            fi
        fi
        sudo tar -xzf "$backup_dir/config.tar.gz" -C /
        sudo systemctl daemon-reload
        if [[ "$stopped" == 1 ]]; then
            sudo systemctl restart zhongan-api zhongan-worker
        fi
        if [[ "$judge_changed" == 1 ]]; then
            tar -xzf "$backup_dir/judge.tar.gz" -C "$judge_dir"
            sudo systemctl restart zhongan-judge-demo
        fi
        sudo nginx -t && sudo systemctl reload nginx
    fi
    printf 'DEPLOY_FAILED backup=%s exit=%s\n' "$backup_dir" "$result" >&2
    exit "$result"
}
trap rollback ERR
if [[ "$backend_changed" == 1 ]]; then
stopped=1
sudo systemctl stop zhongan-api zhongan-worker
if [[ "$judge_changed" == 1 ]]; then sudo systemctl stop zhongan-judge-demo; fi
set -a
. /home/ubuntu/.config/zhongan/database.env
set +a
# The DSN stays in process environment; only its database name is passed to pg_dump.
database_name="$($app_dir/.venv/bin/python -c 'import os,psycopg; c=psycopg.connect(os.environ["ZHONGAN_DATABASE_URL"]); print(c.info.dbname); c.close()')"
sudo -u postgres pg_dump --format=custom --dbname="$database_name" > "$backup_dir/database.dump"
test -s "$backup_dir/database.dump"
pg_restore --list "$backup_dir/database.dump" > "$backup_dir/database-manifest.txt"
fi
changed=1
install -d -m 755 "$app_dir/scripts" "$app_dir/contracts" "$app_dir/docs/medical"
sudo install -d -m 700 -o "$(id -u)" -g "$(id -g)" /home/ubuntu/zhongan-data/web-search
sudo install -d -m 700 -o "$(id -u)" -g "$(id -g)" /home/ubuntu/zhongan-data/judge-recognition
cp -a "$release_dir/scripts/." "$app_dir/scripts/"
if [[ "$backend_changed" == 1 ]]; then
    cp -a "$release_dir/services" "$app_dir/"
    if [[ -d "$release_dir/skills" ]]; then cp -a "$release_dir/skills" "$app_dir/"; fi
    install -d -m 755 "$app_dir/output_dir/memory-ranker"
    install -m 755 "$release_dir/output_dir/memory-ranker/semantix-ranker" "$app_dir/output_dir/memory-ranker/semantix-ranker"
    cp -a "$release_dir/contracts/knowledge" "$app_dir/contracts/"
    cp -a "$release_dir/contracts/medical-services" "$app_dir/contracts/"
    cp -a "$release_dir/docs/medical/knowledge" "$app_dir/docs/medical/"
fi
cp "$release_dir/REVISION" "$app_dir/REVISION"
if [[ "$judge_changed" == 1 ]]; then cp -a "$release_dir/services/judge_demo/." "$judge_dir/"; fi
cd "$app_dir"
if [[ "$backend_changed" == 1 ]]; then
    "$app_dir/.venv/bin/python" -m pip install -r services/api/requirements-rag.txt
    "$app_dir/.venv/bin/python" -m scripts.migrate_database
    "$app_dir/.venv/bin/python" -m scripts.build_knowledge_vectors
fi
"$app_dir/.venv/bin/python" -m pip check
"$app_dir/.venv/bin/python" -c 'from services.api.app.medical_services import catalog; data=catalog(); assert data["benefits"] and data["hospitals"]'
if [[ "$backend_changed" == 1 ]]; then
    sudo install -m 644 "$release_dir/deploy/zhongan-api.service" /etc/systemd/system/zhongan-api.service
    sudo install -m 644 "$release_dir/deploy/zhongan-worker.service" /etc/systemd/system/zhongan-worker.service
fi
sudo install -m 644 "$release_dir/deploy/nginx-zhongan-api.conf" /etc/nginx/sites-available/zhongan-api
# Keep old hashed assets available to already-open browser sessions.
sudo cp -a "$release_dir/apps/web/dist/." "$web_dir/"
sudo install -d -m 755 "$web_dir/.mobile-demo-releases"
if [[ -e "$web_dir/.mobile-demo-releases/$revision" ]]; then
    diff -qr "$mobile_dir" "$web_dir/.mobile-demo-releases/$revision"
else
    mobile_stage="$(sudo mktemp -d "$web_dir/.mobile-demo-releases/staging-XXXXXXXX")"
    sudo cp -a "$mobile_dir/." "$mobile_stage/"
    sudo mv -T "$mobile_stage" "$web_dir/.mobile-demo-releases/$revision"
fi
sudo ln -s ".mobile-demo-releases/$revision" "$web_dir/.mobile-demo-next-$revision"
sudo mv -Tf "$web_dir/.mobile-demo-next-$revision" "$web_dir/mobile-demo"
mobile_switched=1
sudo find "$web_dir" -type d -exec chmod 755 {} +
sudo find "$web_dir" -type f -exec chmod 644 {} +
sudo nginx -t
sudo systemctl daemon-reload
if [[ "$backend_changed" == 1 ]]; then
    sudo systemctl restart zhongan-api zhongan-worker
fi
if [[ "$judge_changed" == 1 ]]; then
    sudo systemctl restart zhongan-judge-demo
    for attempt in {1..20}; do
        if curl -fsS http://127.0.0.1:8010/judge/health > /dev/null; then break; fi
        [[ "$attempt" -lt 20 ]]
        sleep 1
    done
    cmp "$app_dir/services/judge_demo/app.py" "$judge_dir/app.py"
fi
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8000/health > /dev/null; then break; fi
    [[ "$attempt" -lt 20 ]]
    sleep 1
done
sudo systemctl reload nginx
systemctl is-active zhongan-api zhongan-worker nginx
curl -fsS http://127.0.0.1/health
"$app_dir/.venv/bin/python" -m scripts.verify_deployed_release --revision "$revision"
# Once HTTPS is configured, a release must preserve the public TLS entry too.
if [[ -s /etc/nginx/zhongan-https-listener.conf ]]; then
    "$app_dir/.venv/bin/python" -m scripts.verify_deployed_release --revision "$revision" --base https://zhongan.xinzhipingtai.cn
    curl --fail --silent --show-error --max-time 15 https://zhongan.xinzhipingtai.cn/judge/ > /dev/null
fi
printf '\nDEPLOYED_REVISION=%s\n' "$(< "$app_dir/REVISION")"
trap - ERR
