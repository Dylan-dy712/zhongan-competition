#!/usr/bin/env bash
# Run as root on the existing host: enable TLS, verify externally, then redirect.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
mode="${1:-enable}"
[[ "$mode" == enable || "$mode" == redirect ]] || exit 2
source_dir="$(cd -- "$(dirname -- "$0")" && pwd -P)"
domain=zhongan.xinzhipingtai.cn
site=/etc/nginx/sites-available/zhongan-api
tls=/etc/nginx/zhongan-https-listener.conf
redirect=/etc/nginx/conf.d/zhongan-domain-http.conf
exec 9>/home/ubuntu/zhongan-releases/deploy.lock
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
nginx -t
test -f "$site"
backup="$(mktemp -d /var/backups/zhongan-https.XXXXXXXX)"
cp -p "$site" "$backup/site.conf"
for item in "$tls" "$redirect"; do
    if [[ -e "$item" ]]; then cp -p "$item" "$backup/$(basename -- "$item")"; fi
done
printf 'BACKUP_DIRECTORY=%s\n' "$backup"
changed=0
rollback() {
    local result=$?
    trap - ERR
    set +e
    if [[ "$changed" == 1 ]]; then
        cp -p "$backup/site.conf" "$site"
        for item in "$tls" "$redirect"; do
            if [[ -e "$backup/$(basename -- "$item")" ]]; then
                cp -p "$backup/$(basename -- "$item")" "$item"
            elif [[ -e "$item" ]]; then
                mv -- "$item" "$backup/failed-$(basename -- "$item")"
            fi
        done
        nginx -t && systemctl reload nginx
    fi
    printf 'HTTPS_SETUP_FAILED backup=%s exit=%s\n' "$backup" "$result" >&2
    exit "$result"
}
trap rollback ERR
if [[ "$mode" == enable ]]; then
    command -v certbot
    certbot certonly --webroot -w /var/www/zhongan-web \
        --cert-name "$domain" -d "$domain" --non-interactive \
        --agree-tos --register-unsafely-without-email --keep-until-expiring
    test -s "/etc/letsencrypt/live/$domain/fullchain.pem"
    changed=1
    install -m 644 "$source_dir/nginx-zhongan-https-listener.conf" "$tls"
    python3 - "$site" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
include = '    include /etc/nginx/zhongan-https-listener*.conf;\n'
if include.strip() not in text:
    anchor = '    server_name _;\n'
    if text.count(anchor) != 1:
        raise SystemExit('Unexpected application Nginx configuration')
    path.write_text(text.replace(anchor, anchor + '\n' + include, 1))
PY
    install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/zhongan-nginx-reload <<'HOOK'
#!/bin/sh
set -eu
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
HOOK
    chmod 755 /etc/letsencrypt/renewal-hooks/deploy/zhongan-nginx-reload
    systemctl enable --now certbot.timer
else
    # Do this only after an external HTTPS probe succeeds.
    curl --fail --silent --show-error --resolve "$domain:443:127.0.0.1" "https://$domain/health"
    changed=1
    install -m 644 "$source_dir/nginx-zhongan-domain-http.conf" "$redirect"
fi
nginx -t
systemctl reload nginx
curl --fail --silent --show-error --retry 8 --retry-connrefused --retry-delay 1 \
    --resolve "$domain:443:127.0.0.1" "https://$domain/health"
printf '\nHTTPS_MODE=%s\n' "$mode"
openssl x509 -in "/etc/letsencrypt/live/$domain/fullchain.pem" -noout -subject -issuer -dates
systemctl is-active nginx certbot.timer
