#!/usr/bin/env bash
set -euo pipefail
systemctl is-active zhongan-worker
systemctl is-enabled zhongan-worker
sudo -u postgres psql -d zhongan_dev -At <<'SQL'
SELECT status || '|' || count(*) FROM analysis_runs GROUP BY status ORDER BY status;
SELECT 'pages|' || count(*) FROM document_pages;
SELECT 'evidence|' || count(*) FROM evidence;
SQL
systemctl show zhongan-worker -p MemoryCurrent -p CPUUsageNSec --no-pager
journalctl -u zhongan-worker --no-pager -n 20
