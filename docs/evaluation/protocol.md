# 内部效果评测入口 v1

对应spec §11。入口为 `python -m scripts.eval_cli`，仅读取已经授权、冻结的仓库外输入，不联网、不调用模型、不读取数据库。结果永远标记内部口径、`official_metric_verified=false`，不输出真实病历正文。不要将真实金标、运行导出或读者身份表提交Git。

## 冻结元数据

两种命令均要求 `--manifest`；以下键不能为空。代码、模型、prompt、Schema、知识、策略与数据来源必须如实记录，未配置模型不能写live。patient_group_hash指评测方冻结的患者分组文件哈希，不能使用病例数量替代。

```json
{
  "code_version": "实际提交SHA",
  "model_id": "实际模型版本或scripted-test",
  "prompt_version": "实际版本",
  "schema_version": "实际版本",
  "knowledge_version": "实际版本或knowledge:none",
  "policy_version": "已冻结的匹配与评分政策版本",
  "dataset_origin": "synthetic / internal_authorized / official_deidentified",
  "execution_mode": "live / mock / replay",
  "annotation_origin": "内部AI辅助 / 内部专家 / 官方",
  "patient_group_hash": "分组文件SHA256"
}
```

CLI额外计算每份金标、运行文件、盲评表、编号映射、读者注册表和manifest的SHA256，写入结果。它验证字段存在，不替评测方验证授权、患者分组或元数据真实性。冻结、去重、隐藏集隔离须由评测流程执行。

## KR1与KR2

```powershell
python -m scripts.eval_cli --manifest D:/eval/manifest.json --output D:/eval/metrics.json fields --gold-dir D:/eval/gold --runs-dir D:/eval/runs
```

每案金标保持标注包格式：`case_id`、`gold`、`labels`、`_unsure`和`_labels_unsure`。gold包含医院、入出院日期、天数、总额/自付分值及诊断/操作/药名数组。明确不存在用null；标注未完成可不提供该键，两者计数分开。不确定掩码由金标决定，不能根据预测错误动态剔除。未知掩码键拒绝，重复case_id拒绝。

每案运行导出采用**当前API**的facts/insights列表，不是旧原型的encounters/expenses对象。报告待审核时，若extract阶段已completed，KR1仍评分已有抽取；痛点按其自身阶段完成状态独立判断：

```json
{
  "case_id": "synthetic-case-1",
  "status": "completed",
  "stage_results": {"extract": {"status": "completed"}, "insights": {"status": "completed", "model_status": "completed"}},
  "facts": [
    {"fact_type": "diagnosis", "value": "肺炎", "status": "observed", "assertion": "suspected"},
    {"fact_type": "stay_days", "value": 3.5, "status": "observed", "assertion": "present"},
    {"fact_type": "total_cost", "value": {"amount_minor": 12000, "currency": "CNY"}, "status": "observed", "assertion": "present"}
  ],
  "insights": []
}
```

facts可直接使用 `/v1/cases/{case_id}/facts?run_id=...` 响应，insights使用对应接口，status和stage_results使用 `/v1/runs/{run_id}` 响应。金标外部病例号与API UUID不同时，需要评测方提供冻结映射；不可凭文本相似度配案。文件缺失时整案保留为missing；失败/未完成运行作为无自动预测计分。

KR1规则：

- 标量精确匹配；错误值同时FP+1、FN+1，漏值仅FN+1。金额用人民币分，其他货币不得仅比较数字，天数保留小数；不得把现金或自费当作self_paid。
- 实体采用multiset一对一精确匹配，保留断言；重复预测多出的项计FP。只归一化空白，不使用相似度或拆分拼接赚取额外TP。
- 简单金标字符串前缀“疑似/考虑/待排”“未见/否认”“既往”分别对应suspected、negated、historical；其他情况可明确写`{"value":"肺炎","assertion":"suspected"}`，不能把既往或疑似当本次确诊。
- 冲突/缺失等非observed/derived事实不视为自动正确。重复同值标量合并，不同标量值视作未解决，不能取最低费用来匹配。
- 同时报微F1、按病例宏F1、按字段宏F1。零实体机会的F1为null。missing_field_rate是“可判定字段机会中缺预测值”的内部口径，wrong_value单列，不冒充官方缺失率。
- 源材料缺失、不确定、未标注、运行失败与自动运行覆盖分别报告。目前API没有医院/日期/自付fact_type，金标存在时如实记漏提，不从其他值猜出字段。

KR2规则：

- 六类标签只在金标可判定机会评分；金标不确定单列。已完成运行/抽取与completed痛点阶段的缺标签结果，只有语义检测model_status=completed才可视作自动阴性；未配置/失败模型不能凭空给六类阴性。已支持的规则阳性可单独计分。
- pending/candidate/indeterminate、失败或转人工是弃判，不能算自动正确，包括金标阴性。金标阳性弃判还计FN。
- 每个标签输出TP/FP/FN/TN、P/R/F1、严重度一致、阴性比例、弃判和覆盖；整体一致率不能替代逐标签结果。
- 严重度仅对双方阳性且已支持的机会计算。金标“需要核实线索”与预测“确认不合理”不属于同一层级，应在数据政策中固定后使用。

## KR3汇总

```powershell
python -m scripts.eval_cli --manifest D:/eval/manifest.json --output D:/eval/blind_metrics.json blind --scores D:/eval/scoresheet.csv --mapping D:/eval/mapping.json --readers D:/eval/readers.json
```

CSV沿用标注包六列：读者编号、盲评编号、温度感(1-5)、可行动性(1-5)、医学事实错误(有/无/不确定)、备注。固定病例摘要、随机编号与顺序、统一排版和医学审核仍由盲评组织者执行；本命令负责汇总，不伪造独立读者。

映射文件为列表，每份报告一个稳定blind_id：

```json
[{"blind_id":"TEST01","case_id":"synthetic-case-1","disease_code":"FY"}]
```

读者注册表由组织者核验，明确身份与独立性；不能把AI账户注册成人：

```json
{
  "reader-1": {"type":"human","independent":true},
  "AI-annotator-01": {"type":"ai","independent":false}
}
```

同读者同报告重复行全部拒绝，不选最高分。未知编号、空读者、NaN/无穷、范围外/无法评分和缺医学标记单列invalid_rows。每份报告先对有效读者平均，再按病例平均，最后等病例权重汇总，读者多的病例不能获得更多权重。输出病例数、离散程度、病种分布和未评分报告数。

`preview_including_ai`仅供开发预评，永远不能获得正式score_targets_met。只有`registered_independent_humans`中每份报告至少3个独立真人有效评分且温度/行动均分分别≥4才记录评分目标满足。医学错误单列，`medical_review_passed=null`表示尚无独立医学审核结论，不能被温度均分抵消。未生成或安全拦截报告必须在冻结映射中保留，缺评分会使三人覆盖不完整。

## 尚未覆盖的验收

本入口不验证事件关系F1、证据支持、置信度校准、品质画像复算与KR4、病种配对生成、盲包随机化；上述项仍应按spec执行。CLI可运行不是官方数据已跑通、三名真人已评或项目质量门槛全部通过的证明。
