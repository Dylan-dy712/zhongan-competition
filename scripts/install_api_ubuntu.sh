#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

release_dir="/home/ubuntu/zhongan-release"
app_dir="/home/ubuntu/zhongan-app"

test -f "${release_dir}/services/api/requirements.txt"
test -f "${release_dir}/deploy/zhongan-api.service"
test -f "${release_dir}/deploy/zhongan-worker.service"
test -f "${release_dir}/deploy/nginx-zhongan-api.conf"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv nginx

install -d -m 755 -o ubuntu -g ubuntu "${app_dir}"
install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/zhongan-data/documents
install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/zhongan-data/web-search
cp -a "${release_dir}/services" "${app_dir}/"
cp -a "${release_dir}/skills" "${app_dir}/"
cp -a "${release_dir}/scripts" "${app_dir}/"
install -d -m 755 "${app_dir}/contracts" "${app_dir}/docs/medical"
cp -a "${release_dir}/contracts/knowledge" "${app_dir}/contracts/"
cp -a "${release_dir}/contracts/medical-services" "${app_dir}/contracts/"
cp -a "${release_dir}/docs/medical/knowledge" "${app_dir}/docs/medical/"
chown -R ubuntu:ubuntu "${app_dir}"

if [[ ! -x "${app_dir}/.venv/bin/python" ]]; then
  sudo -u ubuntu python3 -m venv "${app_dir}/.venv"
fi
sudo -u ubuntu "${app_dir}/.venv/bin/python" -m pip install --upgrade pip
sudo -u ubuntu "${app_dir}/.venv/bin/python" -m pip install \
  -r "${app_dir}/services/api/requirements.txt"

install -m 644 "${release_dir}/deploy/zhongan-api.service" /etc/systemd/system/zhongan-api.service
install -m 644 "${release_dir}/deploy/zhongan-worker.service" /etc/systemd/system/zhongan-worker.service
install -m 644 "${release_dir}/deploy/nginx-zhongan-api.conf" /etc/nginx/sites-available/zhongan-api
ln -sfn /etc/nginx/sites-available/zhongan-api /etc/nginx/sites-enabled/zhongan-api
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl daemon-reload
systemctl enable --now zhongan-api zhongan-worker nginx
systemctl restart zhongan-api zhongan-worker nginx

for attempt in {1..15}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  if [[ "${attempt}" -eq 15 ]]; then
    systemctl --no-pager --full status zhongan-api
    exit 1
  fi
  sleep 1
done
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1/health
