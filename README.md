# 众安·暖愈智护

众安比赛项目。本仓库按 [众安·暖愈智护 SDD 规格 v0.1](docs/spec.md) 开发；功能完成、官方效果达标与内部质量通过分别验收，规格中的待冻结决策见第 14 节。

## 本地运行

需要 Python 3.11+。安装依赖后运行：

```powershell
python -m pip install -r services/api/requirements.txt
python -m uvicorn services.api.app.main:app --reload
```

访问 `/health` 检查进程，`/openapi.json` 查看由 Pydantic 导出的接口契约。运行验收契约测试：

```powershell
python -m unittest discover -s tests -v
```

## PostgreSQL 开发库配置（Windows）

安装 PostgreSQL 16 Server 与命令行工具 `psql`，安装时设置管理员 `postgres` 密码。项目本机、腾讯云 CVM 与后续腾讯云数据库统一使用 PostgreSQL 16。若 `psql` 不在 PATH，可使用安装目录里的 `bin\psql.exe`。在项目根目录打开 PowerShell：

```powershell
psql -h localhost -U postgres -d postgres
```

在 `psql` 中执行（把示例密码换成仅用于本机开发的密码）：

```sql
CREATE ROLE zhongan_dev LOGIN PASSWORD 'replace-with-local-dev-password';
CREATE DATABASE zhongan_dev OWNER zhongan_dev;
\q
```

随后在 PowerShell 设置当前会话的连接串并建表：

```powershell
$env:ZHONGAN_DATABASE_URL = 'host=localhost port=5432 dbname=zhongan_dev user=zhongan_dev password=replace-with-local-dev-password'
psql -h localhost -U zhongan_dev -d zhongan_dev -v ON_ERROR_STOP=1 -f 'services/api/sql/001_cases.sql'
python scripts/bootstrap_dev.py
```

初始化脚本只建立合成主体、用途授权及高熵开发令牌；令牌仅在终端显示一次。不要将其写入仓库、日志或截图。使用输出的 `subject_id`、`consent_id` 和 `bearer_token` 调用 `/v1/cases`，请求须带 `Authorization: Bearer <token>` 与 `Idempotency-Key`，且 `data_origin` 为 `synthetic`。启动 API 前保持同一个 PowerShell 会话中的 `ZHONGAN_DATABASE_URL`。

当前 API 仅接受合成案件，未配置数据库时返回 503。材料隔离存储、受控文本解析、原生 PDF 文字提取、腾讯云高精度 OCR，以及五类证据绑定字段候选已经实现；图表视觉理解及 LLM 语义抽取尚未接入。不得向此原型上传真实医疗数据。

数据库 API 联调至少验证：有效令牌和授权创建返回 201；同一幂等键与相同内容返回 200 和同一案件；同键不同内容返回 409；跨主体读取返回 404；撤回 `case_guidance` 后读取与重试创建均被拒绝。

腾讯云 CVM `49.235.108.92` 已安装 PostgreSQL 16，项目数据库与基础表迁移已验证。数据库只监听服务器回环地址；运行配置保存在服务器 `/home/ubuntu/.config/zhongan/database.env`，权限为 `600`。本地 Windows 数据库仍需单独安装和初始化。

## 腾讯云当前部署

- PostgreSQL：`127.0.0.1:5432`，仅服务器本机可访问。
- FastAPI：由 `zhongan-api.service` 管理，监听 `127.0.0.1:8000`。
- Nginx：监听公网 80 端口并反向代理 API。
- Parser Worker：由 `zhongan-worker.service` 管理，从 PostgreSQL 队列领取任务。
- 公网健康检查：`http://49.235.108.92/health`。
- 合成测试凭证：仅保存在服务器 `/home/ubuntu/.config/zhongan/dev-fixture.env`，权限为 `600`。
- 材料存储：`/home/ubuntu/zhongan-data/documents`；按案件与文档分目录保存，文件权限为 `600`，不通过响应暴露服务器路径。

部署脚本为 `scripts/install_api_ubuntu.sh`；数据库、API、Parser Worker 与 Nginx 均已设置为开机启动。REQ-01～03 的认证、隔离、授权撤回、按页解析、扫描页 OCR、Evidence，以及诊断、手术、用药、住院天数、医疗总费用五类字段候选已通过真实 PostgreSQL 与腾讯云 OCR 集成检查。字段保留原值、规范值、状态、断言、置信度、单位和来源；缺少材料时显式返回 missing。当前抽取版本 `evidence-pattern-candidate-v1` 是保守规则候选，不代表模型语义抽取或官方效果达标。当前公网入口仍是 HTTP；配置域名和证书前不得传输真实或敏感数据。
