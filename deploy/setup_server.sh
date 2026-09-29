#!/usr/bin/env bash
# 暖愈智护 · 演示服务器一键部署（Ubuntu 20.04+/22.04/24.04）
# 用法：在服务器上进入仓库目录后执行  bash deploy/setup_server.sh
# 数据工件（OCR/bundles/runs）不在 git 内，需从开发机打包上传后解到 ~/work
set -euo pipefail

GREEN() { echo -e "\033[32m$*\033[0m"; }

GREEN "[1/5] 系统依赖"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip curl unzip >/dev/null

PYTHON=python3
if ! command -v $PYTHON >/dev/null; then echo "缺少 python3"; exit 1; fi
GREEN "    Python: $($PYTHON --version)"

GREEN "[2/5] 创建虚拟环境并安装依赖（清华源，失败自动回退官方源）"
cd "$(dirname "$0")/../services/api"
$PYTHON -m venv .venv
PIP=".venv/bin/pip install -q"
$PIP -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi "uvicorn[standard]" pydantic pydantic-settings httpx python-multipart \
    || $PIP fastapi "uvicorn[standard]" pydantic pydantic-settings httpx python-multipart
GREEN "    依赖安装完成"

GREEN "[3/5] 检查 LLM 配置（.env）"
if [ ! -f .env ]; then
  cat > .env <<'EOF'
ZANH_LLM_PROVIDER=zhipu
ZANH_LLM_MODEL=glm-4.5-flash
ZANH_LLM_API_KEY=请填入密钥
EOF
  echo "    已生成 .env 模板，请编辑 services/api/.env 填入 ZANH_LLM_API_KEY"
else
  GREEN "    .env 已存在"
fi

GREEN "[4/5] 检查数据工件（~/work）"
WORK=~/work
for d in ocr bundles runs; do
  if [ -d "$WORK/$d" ]; then GREEN "    ~/work/$d 存在（$(ls $WORK/$d | wc -l) 项）"; else echo "    缺少 ~/work/$d（离线流水线产物，可从开发机上传）"; fi
done

GREEN "[5/5] 完成。启动方式："
echo "    cd services/api && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo "    记得在云控制台安全组放行 8000 端口（建议仅限评审期间开放）。"
