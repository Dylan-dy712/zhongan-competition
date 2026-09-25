#!/usr/bin/env bash
set -euo pipefail
set -a
# shellcheck disable=SC1091
source /home/ubuntu/.config/zhongan/database.env
# shellcheck disable=SC1091
source /home/ubuntu/.config/zhongan/dev-fixture.env
set +a
exec /home/ubuntu/zhongan-app/.venv/bin/python \
  /home/ubuntu/zhongan-app/scripts/check_api_integration.py
