# 持续对话智能体改造

日期：2026-09-27。基础提交：9aec3ec。本文件记录改造与验收范围，不表示官方效果达标。

## 用户行为

- 无报告时可以开始聊天；新对话自动为单个已授权对象建立合成案件，多对象需要选择。
- 对话内上传材料；模型选择是否追问、读取材料、启动分析或检索过去的聊天。
- 工具实际结果反馈给模型；异步分析完成后页面发起幂等续答，刷新不会重复生成。
- 聊天、附件引用、失败状态和工具事件持久化。退出或刷新后可以继续。
- 新会话可以沿用本次案件，或建立新的案件；历史检索限制为同一账号与同一关怀对象。
- 历史回忆开关只控制后续检索，原会话仍可查看；它不是删除功能。
- 补充材料重新分析时，保存旧报告并生成递增版本，修复原先固定 v1 的冲突。

## 技术边界

`conversation_agent.py` 使用供应方原生工具调用，最多 5 次模型请求和 6 次工具执行。普通交流不强制跑完整分析流水线。材料处理仍复用 Worker 的确定性流程，模型无法自选租户身份或任意执行代码。

`conversation_repository.py` 为每次访问核对当前账号、主体访问和用途授权。对话归创建账号所有；即使另一个账号有同主体的案件权限，也无法读取此账号私有聊天。消息使用客户端 UUID 幂等；并发消息被拒绝，崩溃留下的运行中消息在租约到期后可重试。

近期对话受字符预算限制，旧记录通过关键词检索工具读取，附原始时间和记录 ID。目前没有向量记忆、自动偏好档案和后台无人在线续答：页面重新打开后会恢复进度并触发续答。数据库中的完整历史不因上下文截断而删除。

原始证据与已发布报告可供工具读取，待审核报告仅返回状态。引用 ID 必须来自本轮实际工具结果，并再次核对访问权限；这验证引用来源，不等于对每句医疗解释进行了语义正确性证明。

## 新 API

| API | 作用 |
| --- | --- |
| GET /v1/chat/subjects | 可新建案件的授权对象 |
| GET、POST /v1/conversations | 列表与幂等创建 |
| GET /v1/conversations/{id} | 对话、最近消息、分析状态、已发布报告 |
| GET /v1/conversations/{id}/turns?before={turn_id} | 更早消息分页 |
| POST /v1/conversations/{id}/documents | 复用材料验证与隔离存储 |
| POST /v1/conversations/{id}/messages | 持久消息与模型工具循环 |
| POST /v1/conversations/{id}/analyses/{run_id}/continue | 分析结束后的幂等续答 |
| PATCH /v1/conversations/{id}/recall | 控制历史检索 |

旧报告问答 API 保留兼容，新页面不再调用。

## 验证与复现

```powershell
python -m unittest discover -s tests -v
cd apps/web
npm run build
```

数据库集成检查：设置 `ZHONGAN_DATABASE_URL` 后，从项目根目录运行：

```powershell
python -m scripts.check_conversation_integration
```

脚本建立随机 `chat_test_…` schema，运行全部 SQL 迁移、真实 HTTP 路由、上传存储与 Worker，最后清理该测试 schema。模型使用明确的测试替身，不消耗供应方额度，不代表真实模型效果。

本次已在本地 PGlite 0.5.8（PostgreSQL 18.3 WASM）执行该检查，通过 34 项，包括无报告聊天、历史上下文及引用、跨账号隔离、上传解析、续答去重、版本递增、按版本读取旧报告、关闭回忆、模型失败重试、授权撤回和迁移幂等。PGlite 的多连接机制与服务器 PostgreSQL 不同，此结果不能替代 PostgreSQL 16 并发及真实供应方验收。测试引擎依据：[PGlite Socket 官方说明](https://pglite.dev/docs/pglite-socket)。

浏览器检查已验证窄屏布局、服务端历史恢复、新建同案件会话和模型未配置时的保存/重试入口。前端生产构建通过；后端 59 项单元测试通过。

没有本地 PostgreSQL 时，可在单独终端运行：

```powershell
cd tools/chat-test-db
npm ci --ignore-scripts
npm start
```

另一个终端在项目根目录运行：

```powershell
$env:ZHONGAN_DATABASE_URL = 'host=127.0.0.1 port=55439 dbname=postgres user=postgres sslmode=disable connect_timeout=5'
python -m scripts.check_conversation_integration
```

`scripts/preview_chat_fixture.py` 仅用于本地页面检查，提供明确标记的历史夹具，故意不配置模型；新消息会验证真实的错误/重试路径，不能当作智能体演示。退出时删除其临时测试 schema。

## 目标环境验收与发布

- 2026-09-27：在服务器 PostgreSQL 16.15 隔离 schema 运行 61 项单元测试与 41 项集成检查，通过。
- 集成验收包含真实 `deepseek-flash` 对话、读取合成 120 元票据原文并引用、跨新会话检索虚构代号并引用历史；其余权限、上传、Worker、版本及迁移检查使用明确的模型测试替身。没有使用真实病历，不代表大规模模型质量或并发压测达标。
- 真实联调暴露格式不稳定，已增加 JSON 输出约束及最多一次格式修复，仍受总计 5 次调用上限约束。未通过格式或引用校验的输出继续拒绝保存为成功回答，用户可重试；不以模板降级掩盖模型失败。
- API systemd 单元补上 `llm.env`；Nginx 对话请求超时调整为 180 秒。
- 原报告审核/发布链路尚未补齐：此改造不自动放行待审报告，也不新增医学审核界面。

更新入口为 `scripts/deploy_remote.py --host <host> --key <key-path>`，只上传已提交的服务源码、迁移、脚本、通用知识库和构建后的网页，不上传凭据或用户材料。远端 `deploy_update_ubuntu.sh` 先备份应用、网页、配置，停服务后备份数据库，再应用事务迁移并重启。失败会恢复应用与配置；数据库备份保留供人工恢复，不自动覆盖业务数据。新版本就绪前旧前端资源保留。

测试依赖与生产隔离：服务器 Starlette 测试客户端要求 httpx2，验收时装在独立临时目录，并通过 `check_conversation_remote.py --test-deps <path> --live-model` 使用。`--trace-synthetic` 仅用于此隔离合成测试的输出诊断，不用于生产日志。
