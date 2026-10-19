# OCR＋表格结构＋局部VLM：配对实验

## 固定设计

继续使用之前固定的七页开发材料和相同227个金标原子，全部保留，不按分数选页；非官方或独立测试集。原PP GPU960 OCR缓存完全复用，不重新识字。表格模型只恢复版面、行列和单元格，再匹配这些已有OCR文字。全程不读取金标内容决定推理、裁剪或复核目标，不校验原图哈希。

三组全部使用GLM-5.3-Flash专用配置`../local-runtime/private/qianfan-config.json`、v50提示词、vision开启、bbox参数、两并发及`document-fee-taxonomy-exact-v5`含类别计分：

| 组 | 输入与费用处理 |
|---|---|
| A | 原PP GPU960文字＋坐标，既有费用抽取链路 |
| B | 相同OCR＋PP表格结构；禁用局部费用图像复核 |
| C | 与B完全相同的结构缓存；开启局部费用图像复核 |

这轮只隔离费用表阶段：表头/临床字段阶段仍沿用原有整页视觉输入，不能将B称为纯文字或完全无VLM。A的非表格费用阶段也沿用既有图像辅助。B/C对比才用于衡量选择性局部复核的增量作用。

## 表格模型与证据

PP-DocLayout-L、PP-LCNet_x1_0_table_cls、SLANeXt_wired/wireless、RT-DETR-L_wired/wireless_table_cell_det，Paddle TableRecognitionPipelineV2，GPU，关闭自动方向、去畸变和额外OCR，采用清单已冻结的0/180方向。

原OCR矩形框映射到正向原图后送入表格管线。HTML中rowspan/colspan转换成半开行列区间，原生单元格坐标映射回原图。HTML单元格数与框数不一致时拒绝该表的结构接入；结构失败显式记录，保留原OCR作为回退，不能计为结构成功。

每个单元格保留原OCR行索引。置信度只取实际匹配OCR文字的最低分，不冒充结构模型或字段校准置信度；没有可信匹配时为null并标记需复核。金额仍必须与原始金额单元格一致，局部VLM不能绕过金额证据校验。

低OCR名称置信度、文字/几何匹配风险、漏掉名称单元格、金额跨行合并或模型字段置信度不足会触发既有局部裁剪复核。目标由输入和输出冲突决定，不使用金标。B会保留这些未解决标记，C记录复核调用与结果。检查总调用数和局部复核数，避免只报F1不报成本。

## 命令与产物

模型和环境在`../paddleocr-table-local/`。本机隔离环境通过`.pth`复用已有GPU/CPU环境Python包，并在新环境补齐`paddlex[ocr]==3.7.2`。可移植部署应在独立Python3.11环境安装GPU依赖及该extra，不照抄本机绝对路径。

```powershell
../paddleocr-table-local/.venv/Scripts/python.exe -m scripts.paddle_table_experiment --manifest ../preliminary-private/paddle-migration-gpu-frozen7.json --model-root ../paddleocr-table-local/models --output-root ../preliminary-private/paddle-table-hybrid7-ocr --output-manifest ../preliminary-private/paddle-table-hybrid7.json

# A使用原PP清单，B/C使用同一新结构清单；B额外增加此参数：
# --disable-local-fee-review
python -m scripts.preliminary_kr1 infer --manifest ../preliminary-private/paddle-table-hybrid7.json --config ../local-runtime/private/qianfan-config.json --predictions-dir ../preliminary-private/hybrid-v50-local7-predictions --output ../preliminary-private/hybrid-v50-local7-run.json --vision --ocr-layout bbox --workers 2
python -m scripts.preliminary_kr1 score --manifest ../preliminary-private/paddle-table-hybrid7.json --predictions-dir ../preliminary-private/hybrid-v50-local7-predictions --output ../preliminary-private/hybrid-v50-local7-metrics.json --include-inferred-categories
```

A/B/C输出前缀为`hybrid-v50-control7`、`hybrid-v50-structure7`、`hybrid-v50-local7`。重新运行使用新目录，不覆盖旧结果。只有完整七页才作为最终比较。

不写或主动运行测试。验证来自真实表格模型、实际GLM调用和现有标注评分。默认配置和公网部署保持原状，等结果决定是否采用。

来源：[Paddle官方表格管线说明](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/table_recognition_v2.html)。

## 最终结果与版本说明

[完整实测报告](paddle-table-hybrid-results.md)：A/B/C的F1分别为0.7115/0.5042/0.4472，不采用候选。原实验结构为v1（代码9c7d383、协议407664a）。看过结果后，当前代码加入v2名称/金额列门槛，因此当前命令生成的是受保护的新结构；不得将它冒充原A/B/C。需要复现原结构，应固定原代码版本或对已保存的v1缓存评分。

门槛实跑七页后没有可接入表格，全部回退。已比较传给抽取器的text、lines、tables与原PP缓存完全相同，没有再调用LLM，也不新增一个F1声称。证据为私密产物`paddle-table-hybrid-gated-input-comparison.json`。
