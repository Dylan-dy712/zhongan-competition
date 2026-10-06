# 众安·暖愈智护

统一应用位于 `apps/web`：账号注册/登录 → 理赔资料整理 → 上传与关怀对话 → 就医记录与已发布报告。已复用原 Demo 的品牌素材与三步资料流程，资料通过真实 API 保存。`output_dir/product-design/home-proposal.html` 保留为设计参考。部署配置将旧 `/mobile-demo/` 入口跳转到统一应用 `/#/claim`；这项代码变更尚未表示服务器已更新。

账号功能使用数据库迁移 `020_accounts.sql`，启动前执行 `python -m scripts.migrate_database`。密码采用随机盐 scrypt 哈希；登录为 12 小时可撤销会话。注册可暂不授权关怀，登录后在“我的”中单独授权或撤回；不捆绑资源匹配、长期记忆与评测用途。新对话默认关闭历史回忆。理赔资料整理会创建关怀记录，不会向保险公司提交理赔申请。仅使用合成资料。

切片设计与验收范围见 [账号与统一入口](docs/requirements/accounts-and-unified-entry.md)。前端验证运行 `npm run test:auth`、`npm run test:navigation`；账号测试为 `python -m unittest discover -s tests -p test_accounts.py -v`。配置专用 `ZHONGAN_AUTH_TEST_DATABASE_URL` 后，测试将在独立临时 PostgreSQL schema 中执行注册、主体隔离、授权、撤回、登录、退出与过期校验；未配置会明确跳过数据库测试。

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

## 内部评测

内部KR1/KR2及KR3汇总可使用 `python -m scripts.eval_cli`。当前API导出、冻结manifest、不确定标注剔除、失败样本保留与独立真人注册口径见 [内部评测协议](docs/evaluation/protocol.md)。AI辅助标注和预评分不能替代官方评测或真人盲评。

品质画像与需求解释核心使用 `python -m scripts.quality_cli`，七维定义、来源归因、拒排与尚未接入的在线链路见[品质画像说明](docs/reviews/quality-profiles.md)。合成覆盖不代表真实机构或官方KR4达标。

当前逐项实现证据与未通过门槛见 [2026-10-03质量验收记录](docs/reviews/quality-evidence-20261003.md)。工程路径通过与比赛KR达标分开记录。

PR及main通过[GitHub Actions检查](.github/workflows/ci.yml)后，按[CI与云端同步流程](docs/reviews/ci-cloud-deployment.md)部署确切main提交和对应CI网页产物；SSH私钥保持本机使用。

## 持续对话与材料分析

患者端位于 `apps/web`，使用 React、TypeScript 与 Vite。关怀首页、指引阅读和按案件分组的记录页已复用新增前端分支的视觉，继续连接原有聊天、上传、证据和反馈接口；展示契约与验证限制见[患者端关怀体验](docs/reviews/patient-care-experience.md)。持续聊天入口：连接访问令牌后可直接开始，不需要预先输入报告版本。支持聊天内上传 PDF/图片/UTF-8 文本、恢复历史会话、补充材料和查看证据；可另开对话接续同次就医，也可开始新的就医案件。

模型通过原生 `tool_calls` 按需求选择查看材料、启动分析、查询状态、读取原文、读取已发布报告或检索历史。每轮最多 5 次模型调用、6 次工具执行。上传的材料由现有 Worker 处理；页面轮询真实状态，分析结束后使用幂等请求继续回答。不存在按关键词返回固定回答或演示回退。

聊天和工具事件写入 PostgreSQL。近期聊天进入上下文，较早聊天通过同一用户、同一关怀对象的关键词检索查找；关闭“允许新对话回忆”后，该会话不再作为历史检索来源。此版本是可追溯历史检索，不含自动偏好提炼、向量语义检索或物理删除能力。授权撤回后不再允许读取相关对话。尚未发布的报告不会通过聊天绕过审核。

报告校验采用 `report-safety-v3`：引用存在不能证明改写后的事实正确；自动保留完整原文事实，其他病例事实改写进入待复核。行动建议同样校验来源并拦截自行停换加药；无直接来源的复诊日期清空并要求复核。报告模型必须返回完整六节，原始引用摘录保留在审计记录中。此校验是保守发布门槛，不能替代医学审核或官方效果评测。

报告已接入统一审核队列：授权医学审核者可批准、修改生成新版本或驳回，修改保留原版内容和决策审计；报告决策须携带`Idempotency-Key`。批准进入ready；独立publish接口核对材料、授权、审核、知识及安全后原子保存发布与APP待触达记录。APP拉取提醒、逐身份展示/已读回执及反馈待办已接入；反馈处理闭环已接入（resolve 端点 + 审计列 + 角色/范围/并发校验）；外部渠道真实送达尚未完成。原生 PG 并发验收（release 撤回/发布竞争、质量快照并发）已通过。接口、验证与限制见[报告审核链路](docs/reviews/report-workflow.md)。

启动新版 API 前，先在目标开发数据库执行迁移（从项目根目录运行）：

```powershell
python -m scripts.migrate_database
```

迁移命令读取 `ZHONGAN_DATABASE_URL`，依次执行 SQL 并记录版本哈希。旧库尚无迁移记录时会执行已有幂等迁移；应先备份目标库。最新迁移见 `services/api/sql/019_feedback_resolution.sql`（迁移列表 `services/api/sql/`）。模型仍使用 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_ID`，供应方必须支持 OpenAI-compatible 工具调用。缺模型配置时明确报错并保存失败消息，可用原请求 ID 重试。前端访问令牌仅存在当前浏览器会话存储中。

```powershell
cd apps/web
npm install
npm run dev
```

生产构建：

```powershell
npm run build
```

构建产物在 `apps/web/dist`。Nginx 配置 `deploy/nginx-zhongan-api.conf` 将静态站点作为 `/`，并继续把 `/v1`、`/health`、API 文档转发到 FastAPI。

会话改造说明及验收范围见 [持续对话智能体改造](docs/reviews/conversation-agent.md)。

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

当前 API 仅接受合成案件，未配置数据库时返回 503。材料隔离存储、受控文本解析、原生 PDF 文字提取、腾讯云高精度 OCR，以及五类证据绑定字段候选已经实现。DeepSeek V4.1 Flash 结构化抽取、Schema 校验、一次修复预算、逐字引用验证和冲突合并已经通过合成材料真实调用验收；图表视觉理解尚未接入。不得向此原型上传真实医疗数据。

新运行额外保存有原文依据的费用构成（分类与支付口径分别展示），进入费用事件和关怀报告输入；不把明细合计当总费用，不求和重复/范围未确认的项目，不推算自付比例。契约、发布重查和验证边界见[费用构成说明](docs/reviews/cost-breakdown.md)。

REQ-04 已将有效字段重建为诊断、手术、用药、住院和费用事件，并通过 `GET /v1/cases/{case_id}/events?run_id=...` 返回事件和 `belongs_to_encounter` 关系。没有材料日期时 `occurred_at=null`、`time_precision=unknown`；冲突事实保持 `assertion=unknown` 和 `relation.status=indeterminate`，不按页面顺序推断医学时间关系。

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

部署脚本为 `scripts/install_api_ubuntu.sh`；数据库、API、Parser Worker 与 Nginx 均已设置为开机启动。REQ-01～03 的认证、隔离、授权撤回、按页解析、扫描页 OCR、Evidence，以及诊断、手术、用药、住院天数、医疗总费用五类字段候选已通过真实 PostgreSQL 与腾讯云 OCR 集成检查。字段保留原值、规范值、状态、断言、置信度、单位和来源；缺少材料时显式返回 missing。字段抽取已叠加 B 层 LLM 辅助（extract_llm.py），候选必须带原文引用并锚定回页/行；确定性规则层与 LLM 候选层合并（冲突规则层优先）。不代表官方效果达标。当前公网入口仍是 HTTP；配置域名和证书前不得传输真实或敏感数据。

LLM 使用服务器端 `/home/ubuntu/.config/zhongan/llm.env` 注入：`LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_ID`。未配置时运行结果明确记录 `model_status=not_configured`；不会回放固定模型结果。模型输出、修复输出、候选、用量、模型 ID、Prompt 版本和错误状态分别写入 PostgreSQL。
