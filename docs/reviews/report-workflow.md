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

当前没有报告发布API或触达outbox。ready仅表示报告内容审核阶段完成；未决疑点、事实冲突、当前输入版本、知识获准状态、授权与记忆来源、发布/撤回并发仍须在后续原子发布门槛验证。审核人不能用本接口批准知识包或跳过这些门槛。本轮不代表官方KR指标或真实模型质量已通过。
