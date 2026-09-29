# zhongan-competition
众安比赛项目 · 暖愈智护（基于理赔医护记录的医护洞察与温度指引引擎）

## 文档

- [技术方案书](docs/solution.md)：架构、关键技术、验证方案、合规、上线计划（提交主文档）
- [SDD 规格](docs/spec.md)：产品需求、数据与 API 契约、状态机、质量门槛及验收场景
- [决策记录](docs/adr/)：存储选型、LLM 供应商

## 快速开始（原型）

```bash
# 1) 批量 OCR（数据目录含案件子目录；输出 JSON 逐页文本+坐标+置信度）
python scripts/batch_ocr.py --dataset-dir <dir> --ocr-dir <dir> --shard 0 --shards 6  # 起多个分片进程

# 2) 构建案件捆束（分类+分组）
python scripts/build_bundles.py --ocr-dir <dir> --out-dir <dir>

# 3) 端到端流水线（结构化→痛点→温度指引→画像→推荐；ZANH_LLM_* 环境变量配置 LLM）
python scripts/run_offline.py --bundles-dir <dir> --out-dir <dir>            # 全量
python scripts/run_offline.py --bundles-dir <dir> --out-dir <dir> --case CL… # 单案

# 4) API + 演示前端
cd services/api && uvicorn app.main:app --port 8000   # 打开 http://127.0.0.1:8000

# 5) 评测
python scripts/eval_cli.py gold-template --runs-dir <dir> --out gold.json   # 生成金标模板
python scripts/eval_cli.py kr1 --gold-dir <dir> --runs-dir <dir>            # KR1 F1
python scripts/eval_cli.py kr2 --gold-dir <dir> --runs-dir <dir>            # KR2 一致率

# 测试（合成夹具，无真实医疗数据）
cd services/api && python -m unittest discover -s tests
```

服务器部署：`bash deploy/setup_server.sh`（详见脚本注释）。

医疗数据与运行产物一律放在仓库外 `work/`（已 gitignore，见 spec §10.2）。

