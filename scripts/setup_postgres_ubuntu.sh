#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y postgresql-16 postgresql-client-16 openssl

systemctl enable --now postgresql

# Keep the self-hosted development database private to this CVM.
conf_file="/etc/postgresql/16/main/postgresql.conf"
hba_file="/etc/postgresql/16/main/pg_hba.conf"
sed -ri "s/^#?listen_addresses\s*=.*/listen_addresses = '127.0.0.1'/" "${conf_file}"
if ! grep -q '^host[[:space:]]\+zhongan_dev[[:space:]]\+zhongan_app[[:space:]]\+127\.0\.0\.1/32[[:space:]]\+scram-sha-256' "${hba_file}"; then
  printf '\nhost zhongan_dev zhongan_app 127.0.0.1/32 scram-sha-256\n' >> "${hba_file}"
fi

install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.config/zhongan
env_file="/home/ubuntu/.config/zhongan/database.env"
if [[ -f "${env_file}" ]]; then
  # shellcheck disable=SC1090
  source "${env_file}"
  db_password="${ZHONGAN_DB_PASSWORD}"
else
  db_password="$(openssl rand -hex 32)"
fi

sudo -u postgres psql --set=ON_ERROR_STOP=1 --set=app_password="${db_password}" <<'SQL'
SELECT format('CREATE ROLE zhongan_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zhongan_app') \gexec
ALTER ROLE zhongan_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
SELECT 'CREATE DATABASE zhongan_dev OWNER zhongan_app'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'zhongan_dev') \gexec
SQL

umask 077
cat > "${env_file}" <<EOF
ZHONGAN_DB_PASSWORD=${db_password}
ZHONGAN_DATABASE_URL='host=127.0.0.1 port=5432 dbname=zhongan_dev user=zhongan_app password=${db_password}'
EOF
chown ubuntu:ubuntu "${env_file}"
chmod 600 "${env_file}"

systemctl restart postgresql

PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
  --set=ON_ERROR_STOP=1 -f /tmp/001_cases.sql
if [[ -f /tmp/002_documents.sql ]]; then
  PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
    --set=ON_ERROR_STOP=1 -f /tmp/002_documents.sql
fi
if [[ -f /tmp/003_parse_runs.sql ]]; then
  PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
    --set=ON_ERROR_STOP=1 -f /tmp/003_parse_runs.sql
fi
if [[ -f /tmp/004_page_structure.sql ]]; then
  PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
    --set=ON_ERROR_STOP=1 -f /tmp/004_page_structure.sql
fi
if [[ -f /tmp/005_extracted_facts.sql ]]; then
  PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
    --set=ON_ERROR_STOP=1 -f /tmp/005_extracted_facts.sql
fi
if [[ -f /tmp/006_model_extractions.sql ]]; then
  PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
    --set=ON_ERROR_STOP=1 -f /tmp/006_model_extractions.sql
fi
if [[ -f /tmp/007_medical_events.sql ]]; then
  PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
    --set=ON_ERROR_STOP=1 -f /tmp/007_medical_events.sql
fi

PGPASSWORD="${db_password}" psql -h 127.0.0.1 -U zhongan_app -d zhongan_dev \
  --tuples-only --no-align --command \
  "SELECT current_database(), current_user, current_setting('server_version'), (SELECT count(*) FROM information_schema.tables WHERE table_schema='public');"

ss -lnt | grep '127.0.0.1:5432'
echo "PostgreSQL setup complete; credentials saved with mode 600."
