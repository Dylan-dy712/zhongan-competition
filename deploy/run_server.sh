#!/usr/bin/env bash
# 启动演示服务（后台运行 + 日志）
set -euo pipefail
cd "$(dirname "$0")/../services/api"
mkdir -p ~/logs
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > ~/logs/zanh.log 2>&1 &
echo $! > ~/logs/zanh.pid
sleep 2
curl -s http://127.0.0.1:8000/v1/health && echo "" && echo "PID: $(cat ~/logs/zanh.pid)，日志: ~/logs/zanh.log"
