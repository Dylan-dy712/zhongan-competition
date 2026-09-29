# 内部评测标注手册（v0.1）

用途：构建 KR1（结构化字段金标）与 KR2（痛点金标）的**内部口径**评测集。
官方未发布标注集；本手册产物不得称为"官方标注"，报告中一律标注"内部金标"。

## 流程

1. `python scripts/eval_cli.py gold-template --runs-dir <runs目录> --out gold_template.json`
   生成带机器预测值的模板（`_pred_for_reference` 字段仅供核对，**最终以你阅读 OCR 原文后填写的 `gold` 为准**，不要照抄预测值）。
2. 标注人打开 `work/bundles/<case_id>.json`（或通过演示前端"结构化事实"页），逐字段核对原文。
3. 每案产出一份 `gold/<case_id>.json`，放入金标目录后运行：
   `python scripts/eval_cli.py kr1 --gold-dir <gold目录> --runs-dir <runs目录>`

## KR1 字段填写规则

| 字段 | 规则 |
| --- | --- |
| hospital | 材料中出现的主诊机构全称（去掉"（副本）"等后缀） |
| admission_date | 住院案=入院日期；门诊案=最早的就诊/检查/报告日期，格式 YYYY-MM-DD（只精确到月时填 YYYY-MM 并在备注注明） |
| discharge_date | 出院日期；纯门诊案填 null |
| stay_days | 材料明示的住院天数；无明示时按 出院-入院 计算（同日计 1） |
| total_cost_minor | 总费用（分）。多个来源不一致时以医保结算单 > 病案首页 > 发票 > 费用清单合计 为序 |
| self_paid_minor | 结算口径自付（分）；区分"自付"与"自费/目录外"，填自付 |
| diagnoses | 全部诊断（含门诊/入院/出院/病理角色），去重；按原文表述，不翻译不缩写 |
| procedures | 手术与操作名称（含门诊操作），跨行断裂的合并为完整名称 |
| medications | 出院带药与门诊处方药品名（不含耗材敷料） |

判定口径：字段在材料中**确实不存在**时填 null（不算错）；材料有但机器没抽到 = 漏报（FN）。

## KR2 标签判定规则（六类）

对每案每标签给出 `present`（true/false）与 `severity`（low/medium/high）：

| 标签 | 判定为 present 的条件 | severity 参考 |
| --- | --- | --- |
| CLIN_MEDICATION_CONTEXT_REVIEW | 药品与诊断间存在需要医学知识才能解释的错位，且材料未提供解释线索 | 涉及高风险药物（抗凝/胰岛素等）=high |
| CLIN_EXAM_JUSTIFICATION_REVIEW | 同类检查频次明显超出该病情常规（需排除术后监测、病情变化的合理解释） | 低危检查=low，有创/高额=medium |
| COST_SELF_PAY_DEVIATION | 相对同类病种（凭标注人经验估计）自付占比显著偏高（>50% 或明显高于常见水平） | 影响较大的=medium |
| COST_AMOUNT_RECONCILIATION | 不同材料的总金额确实不一致（排除四舍五入 ≤1 元） | 差异>5% =medium，>20% =high |
| EXP_TERMINOLOGY_BARRIER | 诊断/手术记录中存在普通患者难以理解且未附解释的术语 | 存在=low（体验类一般不高于 low，多处/关键决策相关=medium） |
| EXP_DISCHARGE_GUIDANCE_GAP | 出院材料书面缺少复诊/用药/康复/预警指引中的≥1 项（仅书面缺项，不断言口头未告知） | 缺 1 项=low，≥2 项=medium |

**反例（不判 present）**：术后 3 天内每日血常规（合理监测）；金额差 0.5 元（舍入）；材料整体无费用页（用 null 处理，不计机会）。

## 盲评（KR3）另见 spec §11.4；量表与随机化由评测脚本支持（待实现：编号/顺序随机化）。
