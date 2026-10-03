# 报告审核与纠错链路

对应SDD REQ-06/07。统一审核队列支持`target_type=insight|report`，报告对象包含六部分正文、行动、证据、输入与授权版本、历史校验错误。新增迁移`012_report_reviews.sql`为历史pending_review报告补队列；重复执行不重复创建。

## 接口契约

使用现有`GET /v1/reviews`和`POST /v1/reviews/{id}/decision`。报告决策必须携带`Idempotency-Key`；正文仍为`expected_version, decision, reason, corrections`。角色、案件范围、实时用途和授权主体均由服务端核验；撤回后连已成功请求的幂等重放也不返回报告审核内容。

- `approve`：只能处理当前pending_review版本。重新检查正文与行动来源、安全约束；历史安全/来源错误不能靠批准清空，需先correct或reject。通过后进入ready，待审claim标为approved；不自动published。
- `correct`：corrections允许sections、actions，每个字段最多一次，replacement为完整契约对象列表。保留当前六节和来源范围；禁止引入外部案件证据、新知识引用、行动执行状态或虚构时间。修改通过已有报告校验，产生新的case级report_version、report_id、action_id及review_parent_id；原版正文和行动保持不变，状态改为rejected，新版pending_review并进入新审核任务。
- `reject`：当前pending_review报告进入rejected，记录决定与服务端审核身份/时间。

决定返回`result_report_id`定位correct产生的新报告。相同身份/幂等键/正文重复请求返回同一决策；同键不同正文、陈旧版本或已决任务返回409；无访问范围、无有效用途返回404，角色不足403，内容或来源不合法422。新材料生成更高版本时取消旧报告待审任务。Worker和审核共享案件事务锁，版本分配在案件行锁内完成。

## 验证与尚未实现的门槛

`python -m scripts.check_review_integration`在独立可销毁SQL schema通过真实HTTP验证历史报告补队列、患者/停用角色阻断、用途撤回/到期、越界引用、危险内容、原版内容不变、新版与行动归属、幂等重放及冲突、陈旧版本、批准仍对患者隐藏、驳回、撤回后重放拒绝。

`python -m scripts.check_conversation_integration`通过真实Worker验证报告待审任务创建和新材料取消旧任务；模型使用明确测试替身，材料为合成输入。

ready仅表示报告内容审核阶段完成；审核人不能用报告审批批准知识包或跳过发布门槛。本轮不代表官方KR指标或真实模型质量已通过。

## 原子发布与待触达记录

新增`POST /v1/cases/{case_id}/reports/{version}/publish`，必须带Idempotency-Key，正文为`{"expected_version": 版本号}`。只有有案件范围、有效用途的medical_reviewer可发布。发布记录、published状态和APP care_outbox记录在同一事务写入；旧published版改为superseded。outbox初始pending，不表示已经通知患者。

发布核对当前最高报告版本、解析/抽取完成、五类字段输出、当前全部文档版本和source_hash、输入哈希、未决审核和临床驳回、事实冲突、行动所依赖的疑似/否定/既往/unknown事实、报告审核记录、正文与行动来源、安全策略版本、知识版本/病例适用性/获准状态、授权ID/版本/用途及实时期限。尚无可验证记忆来源时，有memory_refs的报告保持未发布；不回退到模型自称可信。

患者、客服/评测角色、助手与聊天工具读取必须经过发布记录和实时授权版本检查；仅medical_reviewer可在案件范围读取审核用草稿。撤回或重新授权为更高版本时，旧发布不能复活；历史superseded报告在其发布授权仍有效时可读。读取时也核对当前知识与安全策略，未完成claim不返回。

`python -m scripts.check_release_integration`运行真实HTTP/SQL，覆盖上述主要拒绝条件、获授权发布、幂等重放/冲突、读取隔离、未获准知识不能被报告审批越过，以及失败不留下半发布状态。输入是明确合成SQL夹具，不能证明生成报告的医学质量或KR指标。

PGlite协议适配器在数据库错误后存在回滚响应问题，因此该环境只验证应用异常引发的实际事务回滚，输出`sql_error_rollback=not_tested_pglite_protocol_limit`与`concurrency=not_tested_pglite_protocol_limit`。原生PostgreSQL执行触达表触发器异常的数据库回滚用例，以及实际多连接的授权撤回/发布竞争和同键重复发布；不能把outbox条数当作触达成功率。

2026-10-03，在用户提供的云服务器PostgreSQL 16.15隔离测试schema中通过94项单测、审核HTTP/SQL、43项聊天/Worker检查及64项发布/触达/反馈检查。发布检查输出`sql_error_rollback=passed, concurrency=passed`：真实SQL异常回滚发布记录和状态；撤回先持有行锁并提交则发布被阻断；发布先持有授权锁则撤回等待，随后患者读取立即隐藏；同时同键发布仅保存一份发布及outbox。竞争检查用`pg_blocking_pids`确认实际阻塞，不以线程启动或睡眠时间猜测发生竞争。此结果不覆盖所有数据库竞态、负载或部署恢复，也不是医学质量评分。

远端隔离入口沿用`python -m scripts.check_conversation_remote --host <host> --key <本机私钥路径> --test-deps <远端临时测试依赖目录> --suite all`；suite也可选conversation/review/release，默认conversation。源码进入随机临时目录，各检查仅创建/清除自己的随机schema；不部署、不重启API/Worker，数据库与模型凭据不输出。未带`--live-model`时不调用真实模型，不能宣称本次真实模型已验收。

## APP提醒、回执与反馈

迁移`014_delivery_feedback.sql`保存每个身份的回执和不可覆盖的反馈。以下写接口必须带Idempotency-Key，同身份同键同正文重放原记录，同键不同正文409；访问检查先于重放。

- `GET /v1/cases/{case_id}/deliveries`：仅patient身份，核验案件范围、实时用途、发布授权版本、知识与安全策略。只返回当前最高版本且已发布的APP提醒；新报告仍在待审时隐藏旧提醒。文案不包含诊断或费用。读取本身不产生展示回执。
- `POST /v1/deliveries/{outbox_id}/receipts`：正文`state=presented|read, expected_version`。版本从0到presented/1，再到read/2；不能跳级。前端实际渲染提醒后提交presented，进入报告面板后提交read。均为客户端报告，不能证明用户理解内容；另一个获授权身份不继承此前身份的已读。首个read将outbox标为acknowledged，逐人状态仍以delivery_receipts为准。每次写入及重放重新核验报告可见性。
- `POST /v1/feedback`：正文`report_id, report_version, action_id?, type, text?`。type支持helpful/not_helpful/inaccurate/needs_help；text最大4000字。绑定实际可读的报告版本及其行动，保留授权快照。历史报告仍可针对其明确版本反馈；反馈不改写医学事实或行动执行状态。
- `GET /v1/feedback/triage`：限获授权医学审核者和客服，核验案件范围、当前授权及反馈授权版本。审核者看到inaccurate/needs_help，客服仅看到needs_help。仅返回pending；撤回或授权换版即隐藏。

报告页面包含查看提醒、已查看状态、四种反馈按钮，只在服务器确认后显示已记录。inaccurate/needs_help进入pending，其余为not_required；页面如实写“等待处理”。暂未接入待办解决接口、客服工单、短信/企微送达或自动随访，不能声称求助已被响应。反馈不是人工盲评，也不用于直接计算KR3温度评分。

发布集成脚本另覆盖无范围身份不得读取/写入、逐人回执隔离、旧提醒随报告换版隐藏、反馈版本归属、客服与医学队列隔离、撤回/换授权后的重放拒绝。`scripts.preview_chat_fixture`提供带显式界面测试标记的报告，仅用于本地页面和回执/反馈验收，不是模型生成或发布医学质量证明。
