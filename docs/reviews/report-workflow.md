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

新增`POST /v1/cases/{case_id}/reports/{version}/publish`，必须带Idempotency-Key，正文为`{"expected_version": 版本号}`。只有有案件范围、有效用途的medical_reviewer可发布。发布记录、published状态和APP care_outbox记录在同一事务写入；旧published版改为superseded。outbox目前仅pending，不表示已经通知患者。

发布核对当前最高报告版本、解析/抽取完成、五类字段输出、当前全部文档版本和source_hash、输入哈希、未决审核和临床驳回、事实冲突、行动所依赖的疑似/否定/既往/unknown事实、报告审核记录、正文与行动来源、安全策略版本、知识版本/病例适用性/获准状态、授权ID/版本/用途及实时期限。尚无可验证记忆来源时，有memory_refs的报告保持未发布；不回退到模型自称可信。

患者、客服/评测角色、助手与聊天工具读取必须经过发布记录和实时授权版本检查；仅medical_reviewer可在案件范围读取审核用草稿。撤回或重新授权为更高版本时，旧发布不能复活；历史superseded报告在其发布授权仍有效时可读。读取时也核对当前知识与安全策略，未完成claim不返回。

`python -m scripts.check_release_integration`运行真实HTTP/SQL，覆盖上述主要拒绝条件、获授权发布、幂等重放/冲突、读取隔离、未获准知识不能被报告审批越过，以及失败不留下半发布状态。输入是明确合成SQL夹具，不能证明生成报告的医学质量或KR指标。

PGlite协议适配器在数据库错误后存在回滚响应问题，因此该环境只验证应用异常引发的实际事务回滚，输出`sql_error_rollback=not_tested_pglite_protocol_limit`。测试脚本在原生PostgreSQL上保留触达表触发器异常的数据库回滚用例。发布/撤回并发当前输出`concurrency=not_tested`，仍须原生数据库验收。APP待触达消费、送前复核、用户确认/反馈、外部渠道均未完成；不能把outbox条数当作触达成功率。
