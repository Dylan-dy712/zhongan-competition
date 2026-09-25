#!/usr/bin/env bash
set -euo pipefail

systemctl is-enabled postgresql
systemctl is-active postgresql
pg_isready -h 127.0.0.1 -p 5432
stat -c '%a %U %G %n' /home/ubuntu/.config/zhongan/database.env

sudo -u postgres psql -d zhongan_dev -At <<'SQL'
SELECT current_setting('listen_addresses');
SELECT rolname || '|' || rolsuper || '|' || rolcreatedb || '|' || rolcreaterole
FROM pg_roles WHERE rolname = 'zhongan_app';
SELECT string_agg(tablename, ', ' ORDER BY tablename)
FROM pg_tables WHERE schemaname = 'public';
SQL

# shellcheck disable=SC1091
source /home/ubuntu/.config/zhongan/database.env
[[ "${ZHONGAN_DATABASE_URL}" == *"dbname=zhongan_dev"* ]]
[[ "${ZHONGAN_DATABASE_URL}" == *"user=zhongan_app"* ]]
PGPASSWORD="${ZHONGAN_DB_PASSWORD}" psql -h 127.0.0.1 -U zhongan_app \
  -d zhongan_dev -Atc 'SELECT 1'

ss -lnt | grep '127.0.0.1:5432'
if ss -lnt | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]):5432'; then
  echo 'PostgreSQL is unexpectedly exposed on all interfaces' >&2
  exit 1
fi
