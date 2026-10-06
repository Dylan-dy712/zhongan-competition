# 账号与统一入口切片（设计、契约与验收）

基线：`spec（必读文件）.md` ZANH-SPEC-001 v0.1.0；对应 REQ-01、11、13 与 AC-15、16、26、28、39、42。本切片不代表完整规格或官方 KR 已验收。

## 行为与不变量

注册使用用户名、显示称呼及密码，不接收外部主体 ID 或角色。服务端新建独立 actor 和 synthetic 关怀 subject，仅建立自己的访问关系；账号与 subject 采用不同 UUID。用户名统一小写。密码 10–128 字符，scrypt 随机盐哈希，不保存明文。

关怀授权可在注册时单独选择，也可登录后确认；未选择仍可注册、登录，不创建用途授权。授权仅覆盖 case_guidance，不包含资源推荐、长期记忆、研究评测。新对话 recall_enabled=false，后续启用沿用现有用户显式操作。我的页面可查看、授予及撤回自己的关怀授权，变更携带 expected_version。撤回后的业务访问仍由既有后端实时权限校验阻断。

登录生成 12 小时 opaque bearer session，数据库仅存 SHA-256；退出撤销当前 session。会话保存在 sessionStorage，刷新恢复、关闭浏览器后不会主动长期保存。遗留开发 actor 继续支持原 token，注册账号不允许使用永久 actor token。

Demo 的理赔准备三步迁入 React，使用同一账号、主题素材及导航。核对确认后实际建立关怀会话、上传资料并提交分析请求；不调用保险理赔裁决系统，不显示理赔提交成功。失败保留明确错误和可重试状态，重试复用 conversation_id、request_id 与已上传资料 ID。既有报告只展示允许发布版本。

## 契约

- POST /v1/auth/register：username、password、display_name、care_consent；201 会话，重复用户名 409，输入不合法 422，限流 429。
- POST /v1/auth/login：username、password；200 会话，统一错误 401，限流 429。
- GET /v1/auth/me：当前账号资料；401 未认证。
- POST /v1/auth/logout：撤销当前 bearer；204。
- GET /v1/me/consents：当前账号自有 synthetic subject 的最新关怀授权摘要。
- POST /v1/me/consents：confirmation、expected_version、Idempotency-Key 请求头；授予或撤回 case_guidance。0 表示未建授权，陈旧版本或同键不同载荷 409。同键同载荷返回已保存结果。

账号契约由 Pydantic 定义并通过 OpenAPI 导出，不含患者医疗正文。数据库迁移 020 仅增加表，不修改已发布迁移。

## 固定验收预期

1. 两个账号注册后 actor、subject 不同；不能读取对方会话、案件、材料或报告。
2. 同名大小写注册冲突；错误密码、停用账号、未知用户名拒绝登录，不泄露密码。
3. 无关怀授权注册可登录，但不能创建关怀；确认后可创建；撤回后不能继续读取相关内容或提交新分析。
4. 过期、撤销及无效 session 均返回 401；退出不依赖只清本地缓存。
5. 三步资料整理调用真实业务接口；重复确认不重复建会话，上传中断可续传已完成文件；模型失败不得用固定样例冒充成功。
6. 页面切换、退出及跨账号切换后晚到请求不能覆盖新空间；注册密码确认错误不发请求。

## 验证记录

2026-10-06：`npm run build` 通过；`npm run test:navigation` 与 `npm run test:auth` 通过（合成 DOM/接口夹具）。后端 `python -m unittest discover -s tests -q` 运行 180 项，179 项通过，1 项原生 PostgreSQL 账号集成测试因未配置专用 DSN 而跳过。密码及身份注入契约测试实际通过，原生数据库中的隔离/会话/授权闭环仍标为未测，不用 mock 结果替代原生 PG 结果。

同日后续验证：用户明确授权后，`scripts/check_accounts_remote.py` 将必要源码上传到现有服务器的临时测试目录，并通过现有数据库连接创建独立临时 PostgreSQL schema，运行账号测试 4 项全部通过、无跳过。实际验证注册及用户名大小写冲突、独立主体、跨账号会话读取 404、用途授予及撤回、同键重放/不同载荷冲突/新键陈旧版本冲突、密码登录、服务端退出和会话过期。测试结束删除 schema 与临时源码/依赖目录；线上应用源码、现有业务表及运行服务未更新。

复查修复了授权版本语义：只有同 Idempotency-Key 的同载荷可复用旧结果，新键携带陈旧版本返回 409；到期的用途显示 expired。部署脚本改为核对根应用及不可变历史产物的版本标记，同时检查旧入口跳转与账号 OpenAPI 路由，避免重定向触发错误回滚。

Chromium 实际加载生产构建产物，320、390、1280 像素宽度均无横向溢出，注册提交按钮可滚动到达，无页面异常；截图和机器记录位于 `output_dir/unified-auth/`。测试中本地路由直接返回构建文件，未访问实际 API 或数据库。CI 已增加账号流程测试和专用 PostgreSQL 测试 DSN，但本次未触发或声称远端 CI 通过。

真实保险系统集成、授权保留期限、外部身份验证、密码找回与完整医疗合规策略不在本切片已验证范围。仅在临时 schema 执行迁移；未执行业务库迁移或服务器部署。账号 JSON Schema 和新增前端类型由 `python -m scripts.export_account_contracts` 从 Pydantic 生成。
