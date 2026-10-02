# 报告证据保真与发布门槛

对应 SDD REQ-07、病例事实溯源与行动时间来源契约。策略版本 `report-safety-v2`，报告提示词版本 `six-section-care-report-v2`。

## 问题与结果

原实现只判断引用ID存在：原文为“疑似肺炎”，报告仍可能把“确诊肺炎”标为无需审核；行动建议未经过同样的内容校验。Worker绑定引用时还通过 `pop` 删除了模型原始摘录，导致审计记录丢失来源线索。

现在先复制草稿再绑定证据。对病例事实和行动，只有保留完整来源语句才能自动通过；包含真实摘录但改写了否定、疑似、既往或其他限定的文本进入待复核。白空格、句末中文句号和诊断标题可归一化，其他改写一律保守处理。合法引用仍不能证明事实语义正确，此策略不是医学理解模型。

## 验收契约

| 输入或条件 | 预期结果 | 验证 |
|---|---|---|
| “疑似肺炎”来源对应“确诊肺炎”报告 | 病例事实pending，保留证据，报告pending_review | `test_real_quote_does_not_auto_approve_contradictory_fact` |
| 仅截取“未见肺炎”或“肺炎，待排”的“肺炎” | 不自动批准 | `test_substring_cannot_drop_negation_or_pending_qualifier` |
| 从否定或既往用药截取服药行动 | ACTION_REQUIRES_REVIEW | `test_action_substring_cannot_turn_history_or_prohibition_into_instruction` |
| 自行停药/换药/加药行动 | 删除并记录错误；明确禁止自行停药的原文可保留 | `test_unsafe_action_is_removed_but_prohibition_is_retained` |
| 有引用但复诊日期无原文依据 | 清空due_at并待复核 | `test_invented_deadline_is_removed_and_action_requires_review` |
| 用户提醒被标成医嘱日期 | 清空日期与错误来源类型 | `test_user_request_cannot_be_labeled_as_medical_order` |
| 日期无时区、纯日期、自然语言 | Action契约拒绝 | `test_action_contract_rejects_natural_language_or_naive_deadline` |
| 报告缺节/重复节 | 模型草稿Schema拒绝，使用现有一次结构修复机会 | `test_duplicate_or_missing_draft_sections_fail_schema` |
| 引用未知报告结论或外来证据 | 助手整个回答失败，不仅删引用保留正文 | `tests/test_care_assistant.py` |
| Worker生成矛盾事实与非法行动 | SQL中报告待复核、危险行动删除、虚构日期清空，审计原草稿不变 | `scripts/check_conversation_integration.py` |

## 验证方式与限制

测试只使用合成材料；SQL集成运行在可销毁独立schema，模型调用为明确测试替身。未将真实病历或AI标注包加入仓库；这些测试不能代表真实模型质量或官方KR指标。

门槛有意保守：长证据段中的正确改写也可能进入待复核，中文相对医嘱时间尚未解析为具体日期。当前未注册可验证的service_policy时间来源，不能让模型自行声明政策日期。后续应在医学复核和带来源的时间解析完成后放宽，而不是靠降低校验强度提高自动通过率。

本轮不新增报告审批/发布接口，也不声称解决了医生或患者角色归属、跨次就诊费用合并、完整医学事实验证。该审批链路和真实模型评测仍是后续工作。
