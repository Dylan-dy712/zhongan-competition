# 初赛结果与复现说明（2026-10-13）

本轮以更新后的 KR 图片为工作目标。KR1 的 F1≥0.90、缺失率<5%不变；KR2要求三类至少五种痛点及归类原因；KR3覆盖三病种；KR4允许虚构数据构建产品方案；KR5要求完整链路原型。是否替代原版所有评分条款仍需主办方确认。

## 结果边界

| 项目 | 已有结果 | 当前不能声称的结果 |
|---|---|---|
| KR1 | 70案件、728原图与参考JSON的冻结映射；模型只读取原图/OCR，不读取答案；字段置信度、出处与待复核标记 | 官方KR1达标、五类核心字段全覆盖、未知30份独立集通过 |
| KR2 | 合成材料上实际调用模型，覆盖临床2种、费用1种、体验2种；展示归类原因、原文、行动 | 专家痛点一致率或真实样本全部达到要求 |
| KR3 | 骨折、肺炎、冠心病4份合成情境，实际模型生成六节草稿；同病种不同照护情境对照 | 真人盲评分数、医学批准、真实病例效果 |
| KR4 | 120条合成记录生成33画像；3病种×5机构，五有效维度，30种关注点组合各有两条理由 | 真实医院品质、真实患者就医排序 |
| KR5 | 主应用现有上传、分析、医学复核、发布、APP提醒、反馈处理；新增方案演示页 | 新页面已部署、外部企微/短信实际送达、全新环境已完成真实全链路演示 |

### KR1评测口径

每个文档只评参考JSON实际标注的字段机会，失败文档计漏抽；空参考不当作已核实负例。实体多重集一对一精确匹配，仅做Unicode、空白和显式列表格式归一化，不做语义同义替换。费用按原项目名与金额绑定，禁止将单价当金额。

旧 `document-explicit-list-opportunities-exact-v2` 排除 `category_inferred=true` 的费用类别。新增 `document-fee-taxonomy-exact-v3` 将所有有标签的费用类别按标准语义分类计分，包含参考标为推断的类别。两个口径的总体分数不可直接比较。新旧预测必须在同一个口径下重算后再谈提升。

标准费用类别代码与医院项目编号不同。模型输出 `sourceItemCode` 保存原编号；`itemCategoryCode/itemCategoryName` 使用标准词表。推断归类必须有 `category_inferred=true`、原因和置信度，不能冒充原文。分类不判断诊疗是否必要。

20份固定开发材料，v6和v7在v3口径下分别为F1 **0.739484**、**0.877397**；v7缺失率 **0.065169**。这20份不是独立测试集，也不足以宣布全量或官方达标。全量结果需由下面的命令重新生成并冻结。

v7全量728份：704份完成、24份失败；同一v3口径F1 **0.704965**，缺失率 **0.144616**，未达标。费用名称金额F1 **0.715039**，语义分类F1 **0.684940**。不能用上述20份局部结果覆盖全量失分。全量原始预测在仓库外私密评测目录，不含在公开包里。

v8全量728份：701份完成、27份失败；F1 **0.700572**，缺失率 **0.148213**。费用名称金额改善，但诊断提取下降，不能选其局部优势声称整体提升。v9保留原图并增加同页重叠放大图；因供应方余额不可用、接口HTTP402中断，已有541份输出（56完成、482接口失败、3校验失败），另187份没有输出，不能作为完成的全量效果验证。首次OCR规则基线在同一v3口径重算为F1 **0.369734**（633完成、95失败），不与旧v2总体分直接混比。

缺失率当前定义为：某标注字段类别完全未输出时的标注原子数 / 全部标注原子数；错误值仍算FN，但不算完全未输出。它不是主办方已确认的官方缺失定义。整体包含医院名、日期、票据及费用原子，不能替代五类核心字段专项成绩。手术与正文用药缺少独立标准化金标；不得从预测反向制作正确答案。

原始材料校核发现：已有工作目录中18张图片与主办方原始压缩包不一致。已从原始压缩包重新提取728张实际图片，排除Mac资源分叉文件，按原图哈希重新冻结清单；710张沿用哈希一致的OCR，另外18张重新调用OCR（15成功、3失败，失败页仅可走原图视觉抽取）。旧v7/v8成绩保留为历史工作输入成绩，不代表纠正后的原始材料成绩。此前个别“费用标注对应封面”的疑点来自工作图片不一致，不能据此判定专家标注错误。

最新评分口径 `document-fee-taxonomy-exact-v5` 修正两点：仅将明确括号列表解析为实体列表，不按临床句子逗号拆实体；仅对数值字段归一化数值字符串，不改写票据编号和实体名称。历史预测须按新口径统一重算，不能择优混合不同口径。

纠正原图后的GLM-5.3-Flash v12固定前20份开发材料：13完成、4校验失败、3超时；全部计入的F1 **0.780094**，缺失率 **0.317210**，未达标。该轮真实调用，不是Mock，但仍是开发子集；字段精度 **0.969900** 不能替代召回率 **0.652418** 和全量F1。正在修复可选坐标格式导致的整页拒收、空输出及超时，并重新运行；重跑未结束前不宣布达标。

发现原图/参考内容对应疑点时保留原始计分、列出审计候选，不自动重映射、排除或纠正参考。`audit_reference_alignment` 的OCR支持比例只用于定位问题，不能判定标注错误。

## 两种复现模式

### 保存结果模式（无需模型或数据库）

环境：Node.js 24，npm。在项目根目录：

```powershell
npm ci --prefix apps/web
npm run build --prefix apps/web
npm run preview --prefix apps/web -- --host 127.0.0.1
```

打开终端打印的本地网址加 `/#/quality-demo`。可查看三病种六节关怀、五种痛点、两份骨折对照、五维画像及两个关注点理由。页面中的关怀是保存的真实模型输出，输入均为合成材料；不是现场重新生成。

重新计算合成画像（Python3.11+、已安装后端依赖）：

```powershell
python -m scripts.build_quality_demo --output apps/web/src/quality-demo.json --input-output ../reproduction/quality-input.json --full-output ../reproduction/quality-result.json
```

该命令会覆写合成网页数据，不读取医疗原图。首次先创建 `../reproduction` 目录。

### 现场模型与真实材料评测模式

安装 `services/api/requirements.txt`。私密JSON配置由运行者自行提供，含 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_ID`。模型需支持OpenAI兼容Chat Completions和图片输入。配置、原图、OCR与预测均放在仓库外。只有获授权的评测环境可以使用真实材料，不能上传到当前仅接受合成案件的患者原型。

```powershell
python -m scripts.build_care_demo --config ../private/model.json --output-dir ../reproduction/care
python -m scripts.preliminary_kr1 prepare --gold-root <参考JSON目录> --image-root <原图目录> --ocr-root <已有OCR目录> --output ../reproduction/document-manifest.json
python -m scripts.preliminary_kr1 infer --manifest ../reproduction/document-manifest.json --config ../private/model.json --vision --workers 4 --predictions-dir ../reproduction/predictions --output ../reproduction/run.json
python -m scripts.preliminary_kr1 score --manifest ../reproduction/document-manifest.json --predictions-dir ../reproduction/predictions --include-inferred-categories --output ../reproduction/metrics-v3.json
python -m scripts.audit_reference_alignment --manifest ../reproduction/document-manifest.json --output ../reproduction/alignment-questions.json
```

视觉证据是模型转录，坐标尚需独立核对；命中OCR文字也不等于事实改写正确。所有文档预测均 `release_eligible=false`。更换提示词、代码或模型时必须使用新的预测目录，禁止混合旧输出。调用时间和token写入私密结果；实际费用按供应方账单核算，不用估算冒充实测。

患者应用完整链路还需要PostgreSQL16、数据库迁移、API、Worker、知识配置和模型配置，见根README。使用合成材料完成授权→上传→分析→审核→发布→提醒→反馈；审核令牌单独配置。保存结果页面不能替代这段现场操作。

### 暂无模型时的本地Mock

用户已授权先用Mock继续推进。Mock是**已保存结果的接口回放**，不是新推理、不产生准确率或温度感成绩。仅支持本仓库四份固定合成关怀材料；可选加载私密文档预测缓存，原图哈希或OCR文本必须命中注册来源。未知输入明确返回422，不伪造通用答案，不提供自由聊天或工具调用。只监听本机127.0.0.1。

```powershell
python -m scripts.mock_preliminary_model --port 8021
```

运行者在仓库外创建 `mock.json`（内容均为占位配置，无真实密钥）：

```json
{"LLM_BASE_URL":"http://127.0.0.1:8021","LLM_API_KEY":"mock-local-only","LLM_MODEL_ID":"mock-preliminary-replay","LLM_PROVIDER":"mock"}
```

另开终端执行 `python -m scripts.build_care_demo --config ../private/mock.json --output-dir ../reproduction/mock-care`，输出必须标记 `execution_mode=mock`。带文档缓存时，服务启动增加 `--manifest <冻结清单> --predictions-dir <已保存预测目录>`，随后用 `preliminary_kr1 infer` 与上述Mock配置验证数据流。评分器主动拒绝Mock预测，避免将回放记成效果达标。

恢复模型后换回真实配置和全新的结果目录；旧Mock目录不能续跑为真实推理。当前患者应用的完整后台未被替换为Mock，上传、自由聊天与医学发布不能由该回放接口冒充。

## 15分钟投屏顺序

前3分钟用一页KR表展示实际数值、数据版本和未验证项。7分钟演示：0–1分钟真实授权与上传；1–3分钟抽取字段、事件与证据；3–4分钟痛点归类；4–5分钟关怀与骨折情境对照；5–6分钟品质方案与关注点解释；6–7分钟审核发布、APP提醒及反馈。如果分析尚在运行，展示已冻结案件并明确切换，不假装当前上传已完成。

最后5分钟问答准备：为什么不是通用科普；费用归类与医学不合理判定的区别；官方金标覆盖与独立集；合成推荐的边界；证据、授权撤回、模型错误的处置。技术架构、模型版本与分层成本可引用spec和实际运行日志。
