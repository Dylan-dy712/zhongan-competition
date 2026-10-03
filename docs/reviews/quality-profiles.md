# 理赔特征驱动的品质画像与解释核心

对应SDD REQ-08/09。`services/api/app/quality_profiles.py`提供结构化特征契约、七维统计和需求匹配；`scripts/quality_cli.py`从已授权的理赔特征导出计算快照。它是原型计算入口，尚未接入在线推荐权限、PG快照库、Worker recommend阶段或患者界面，不能声称端到端KR4已完成。

## 输入与归因

输入`QualityInput`包含dataset_version、data_origin、entities、records、policy和excluded_encounters。每条记录唯一encounter_id，私有subject_ref用于反馈去重；出院日期与病种/治疗/风险/医保分层共同定义同组。未知、未分层或缺失风险/医保变量可以展示内部描述统计，但不能比较。人民币金额按整数分保存，medical_personal_share只表示统一口径医疗自付，不接受现金付款、自费费用或商业保险后净支出冒充。

机构采用稳定ID映射；医生必须带医院命名空间和材料记录中的角色；方案有规范定义和版本，记录treatment_group必须等于`definition@version`。每条Attribution明确entity_type/entity_id、可归属的metric列表与source_refs；没有归因的维度保留null，不从医院复制到医生或方案。规则审核有passed/decidable/applicable、reviewer_id、rule_version及证据引用；仅统计与冻结政策版本一致的审核。算法不从痛点候选、术语出现或记录完整性推断医学合规。

数值观测、规则审核、随访和反馈均须有UUID来源引用。来源可以是现有证据、审核决定或真实反馈，特征导出与映射应由上游校验并保留；目前输入契约只能验证结构、计数关系和明确归因，不能证明引用对应原文真实支持、审核者确有资质或用途授权仍有效。data_origin和policy的审核元数据也不是密码学证明。未完成这些权威检查前，不能直接把CLI结果作为对患者的可信推荐。特征包及低样本内部统计保存在授权环境，不上传病历/受试者ID到GitHub。

## 七类统计

| metric_name | 当前固定计算 | 有效性边界 |
| --- | --- | --- |
| cost_level | 实体同组总费用中位数/全部同组中位数 | 参照为0不可计算；费用水平不代表疗效或成本效果；排除当前病例后一起重算参照，参照组样本/缺失同样过门槛 |
| self_paid_burden | 有统一口径及匹配总费的自付金额合计/总费合计 | 金额成对可用、总费>0，自付≤总费；不是逐病例比率简单平均 |
| medication_conformity | 通过机会数/可判定适用机会数 | 必须有审核人与冻结规则版本；不声称所有用药合理 |
| treatment_conformity | 通过机会数/可判定适用机会数 | 固定医学标准版本；不是病历字段齐全率 |
| guidance_completeness | 清单记录通过项/可判定适用项 | 固定适用清单版本；仅反映材料记载完整度，不是疗效/体验 |
| readmission_rate | 完整观察的非计划再入院索引病例/完整观察索引病例 | 必须标明计划性已排除、完整随访及observed_until覆盖出院后固定天数；没有后续理赔不能记作0 |
| patient_feedback | 每个respondent最新明确归因索引记录的固定问项1～5均值 | 不由病历/LLM推断，未回答不记满意；先选最新索引再检查问项/回答；最新缺失不沿用旧回答，有效人数与eligible_count分别输出 |

指标版本为`claim-cohort-metrics-v2`，历史v1输出保持原样，新输出使用新快照ID。费用同时输出`reference_sample_count/reference_eligible_count/reference_missing_rate`，自身数据完整不能掩盖参照组缺失超限。

每维保留数值、适用分母/分子、有效样本、缺失率、政策/指标/数据版本、同组ID、窗起止、限制与快照引用。`computable`仅表示有数学上有效的统计；`comparison_allowed`再检查分层、最小样本和缺失/不确定阈值。规则审核的不确定率使用纳入观测中最差病例的不可判定机会比例，保守拒绝相应比较；缺失审核仍计缺失，不用剩余完整病例掩盖。

政策必须显式给出min_sample_size、max_missing_rate、最少五个有效维度、随访天数、标准/问项版本；无隐含业务默认阈值。draft政策始终不能推荐。frozen需审核身份和日期，但实际审批真实性仍应由后续服务核验，不以输入自称已冻结代替正式批准。

## 匹配与拒排

`ProfileMatchRequest`明确病种、治疗、风险、医保组及按优先顺序排列的need_id/metric_name，至少两个不同指标。只有同组且≥5维允许比较、全部明确需求都有有效依据、政策已冻结的候选才产生解释。每条解释给实际值、有效样本、独立metric快照引用与need引用，不生成自由口碑或综合医疗质量分。

排名仅依据用户首选指标及字典固定方向，其他需要仍须有独立解释。先在同类型实体内比较，再检查删一观测范围是否重叠；费用的扰动同时重算参照中位数，出现分母失效也拒排。每次删一重新检查有效样本、缺失及不可判定阈值；费用参照组也重查。排名要求所有明确需求与至少五维在各自删一验证中仍有有效依据，不能只保留首选维度。反馈按删一respondent计算。该范围是敏感性分析，不是统计置信区间，也不能证明因果优势。只有一个可比候选、区间重叠/无效或合成数据均返回ranking_allowed=false；不强行排出先后。输出列表顺序不是可信排名，只有显式rank字段才表示排序。

## 使用与验证

从Pydantic的`QualityInput.model_json_schema()`导出输入Schema，`ProfileMatchRequest.model_json_schema()`导出匹配Schema；`ProfileMetric`与`Recommendation`提供输出Schema，生成结果逐项执行契约验证。特征文件和请求列表放在授权目录，输出路径使用新版本，已有不同内容不可覆盖。

```powershell
python -m scripts.quality_cli --input D:/authorized/quality-features.json --requests D:/authorized/matching-needs.json --output D:/authorized/profile-snapshot-v1.json
```

输出同组快照、逐请求候选与机构覆盖：已有映射机构、具备五个可计算维度、当前分层内五维可比较、满足两条理由、允许排名分别计数。同实体跨分层的metric_ref包含同组ID以免引用混淆；匹配选当前分层，不能返回重复的矛盾候选。`official_kr4_verified=false`始终保留；核心工具不会自行宣布官方达标。

`tests/test_quality_profiles.py`使用显式合成3病种×5机构×4病例，验证七维复算与可追溯解释、受试者信息不进入输出、医疗自付加权、反馈按人去重、随访删失、审核版本缺失、不确定性与未知分层、医院/医生/方案归因隔离、当前病例排除、draft拒绝、排名扰动拒绝及CLI拒绝覆盖。v2补充最近索引未回答/问项变更、完整候选面对80%缺失参照、样本恰达门槛、参照恰达缺失边界及删一后需求/五维失效的回归。修改origin元数据的测试只用于验证排序分支，不是实际历史数据。合成覆盖矩阵证明程序分支，不是官方机构覆盖。

下一步必须接上现有cases/evidence/reviews/feedback的权威特征导出、resource_matching用途及实时授权检查、不可变PG快照和案件推荐接口；再接Worker/报告与患者界面，补医生归因/正式指标政策和真实授权数据覆盖。来源未确认的数据、自动痛点候选和模板化评分不得用于填满雷达维度。
