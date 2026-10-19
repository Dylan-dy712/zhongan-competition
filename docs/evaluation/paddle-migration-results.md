# PaddleOCR 替换实测结果

## 结论

本机选择 **PP-OCRv5 server / GPU / 检测边长 960**，替换腾讯 OCR。七页开发材料的配对抽取总体 F1 从 0.6783 提升到 **0.7217（+4.35 个百分点）**。这支持在本机继续使用该方案，**不代表 KR1 ≥0.90 已达标，也不代表独立测试或全量结果**。

## 固定口径

- 改动前冻结七页：一页倾斜费用单、三页既有表格恢复材料、前三页临床范围材料。没有按分数删除或替换页面。
- 同一 revised-v3 金标，共 227 个计分原子；未修改参考答案或评分器。
- 同一 GLM-5.3-Flash、`document-fields-evidence-v48-paddle-vision-ocr-context`、vision 开启、bbox 行重建、两并发。
- 评分器 `document-fee-taxonomy-exact-v5`，包含推断费用类别；类别复合 F1 同时要求名称、金额和类别匹配。
- 腾讯使用已有缓存（含表格 V3 结构）；PP 对原图重新识别，当前只有文字和坐标，没有表格结构模型。因此比较的是替换方案，不能将差异全部归因于纯 OCR 识别能力。
- 已知 OCR 失败直接记为失败并保留金标分母，不允许绕过 OCR 用视觉模型冒充 OCR 成功。不校验原图哈希。

## 配对结果

| 方案 | 总体 F1 | 名称金额配对 F1 | 类别复合 F1 | OCR 完成 | 最终抽取状态 |
|---|---:|---:|---:|---:|---|
| 腾讯缓存 + v48 | 0.6783 | 0.6569 | 0.6404 | 7/7 | 完成 4、部分完成 3 |
| PP CPU 960 + v48 | 0.6649 | 0.6429 | 0.6190 | 6/7 | 完成 6、失败 1 |
| **PP GPU 960 + v48** | **0.7217** | **0.7157** | **0.6798** | **7/7** | **完成 7** |

总体 TP / FP / FN 分别为：腾讯 156 / 77 / 71，PP CPU 129 / 32 / 98，PP GPU 166 / 67 / 61。三组金标分母均为 227。

| 固定页序号 | 腾讯 | PP CPU | PP GPU |
|---|---:|---:|---:|
| 1 | 0.9565 | 0.9565 | 0.9565 |
| 2 | 0.6533 | 0.7067 | 0.7067 |
| 3 | 0.8293 | 0.8293 | 0.8780 |
| 4 | 0.4526 | 0.0000 | 0.5109 |
| 5 | 0.9412 | 0.9412 | 0.9412 |
| 6 | 0.5000 | 0.5000 | 0.5000 |
| 7 | 0.9167 | 0.9167 | 0.9167 |

PP GPU 的七页原生 OCR 耗时合计 **5.420 秒**，单页中位数 **0.703 秒**、范围 0.328–1.140 秒；不包含模型加载、LLM 抽取和完整 HTTP 链路。CPU 六个成功页合计 770.5 秒，另有一页达到 300 秒预算后失败，不能将失败时间从完整运行成本中抹去。腾讯本轮复用缓存，没有可比的新鲜 OCR 耗时。

金标 100 个费用名称在 OCR 文本中的字面命中数为腾讯 60、PP CPU 36、PP GPU 50。这不是 CER 或费用字段 F1，也说明不能宣称 PP 在所有原始文字识别上都优于腾讯。当前收益来自 OCR 与后续模型组合的最终结果。

GPU 1600 作为额外参数探索仅完成 4/7 页 OCR，后三页服务错误，未继续计算端到端 F1，未选为默认。随后单独重跑其中一页成功，失败根因尚未确定，不能断言是显存或特定图片导致。运行日志出现 cuDNN 编译与运行版本警告，但未证明它是失败原因。

## 复现资料与命令

源码与依赖在仓库；医疗材料、私密模型配置、缓存和逐页预测仅保存在仓库外的 `../preliminary-private/`，不随代码上传。输入清单为 `finals-optimization-fixed7.json`，其清单摘要为 `a212b45a4895ad4f571b1df50f21f29555285da1dc903f475ef47dd701e59ab4`。该摘要是清单版本标识，不是原图哈希校验。

三组清单：`finals-optimization-fixed7.json`、`paddle-migration-frozen7.json`、`paddle-migration-gpu-frozen7.json`；后两组仅引用各自实际 OCR 缓存及摘要，保留同一文档、图片、方向和金标引用。

最终产物前缀分别为 `paddle-migration-v48-strict-tencent-bbox7`、`paddle-migration-v48-strict-paddle-bbox7`、`paddle-migration-v48-gpu-bbox7`，每组保留 `-run.json`、`-predictions/` 和 `-metrics.json`。汇总为 `paddle-migration-comparison-final.json`。

在已具备授权输入、模型私密配置及侧车环境的机器，启动方式见[实验协议](paddle-migration-experiment.md)。重新推理应使用新输出目录，避免把旧预测当作新推理：

```powershell
python -m scripts.preliminary_kr1 infer --manifest ../preliminary-private/paddle-migration-gpu-frozen7.json --config ../local-runtime/private/qianfan-config.json --predictions-dir ../preliminary-private/paddle-gpu-reproduce-predictions --output ../preliminary-private/paddle-gpu-reproduce-run.json --vision --ocr-layout bbox --workers 2
python -m scripts.preliminary_kr1 score --manifest ../preliminary-private/paddle-migration-gpu-frozen7.json --predictions-dir ../preliminary-private/paddle-gpu-reproduce-predictions --output ../preliminary-private/paddle-gpu-reproduce-metrics.json --include-inferred-categories
```

LLM 重新调用可能波动。已有预测的 score 可复算本次结果；新鲜 OCR 和新鲜模型调用应另外记录版本、耗时与失败数。

## 边界与下一步

七页均为已接触开发材料，尚未完成全量或独立评测；没有建立 KR1 全部核心字段的官方达标结论。下一步优先处理仍低分的费用页：检查名称金额错绑与遗漏，再评估表格结构恢复。扩大固定样本覆盖后再决定是否在其他机器或公网替换。

本轮没有新增、修改或主动运行测试。验证依据是实际 OCR、实际模型抽取及其与金标的比较。本机配置切换不代表公网部署完成。
