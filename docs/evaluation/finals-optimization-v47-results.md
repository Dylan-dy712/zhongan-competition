# 抽取优化实际对照：2026-10-18

## 范围与复现

在修改前固定七页开发材料：一页已知倾斜费用单、三页既有表格恢复材料、临床范围开发清单前三页。没有按本轮结果删选样本。它们均属已接触开发材料，不能称为独立测试集，更不能代表全量或官方KR1达标。

清单摘要：a212b45a4895ad4f571b1df50f21f29555285da1dc903f475ef47dd701e59ab4。基线代码35172c6；最终被评估的代码e1529e7。模型均为glm-5.3-flash，两并发，vision开启，plain OCR布局；保持相同OCR缓存、参考版本及document-fee-taxonomy-exact-v5评分器。没有验证原图哈希、修改金标或修改评分逻辑。本轮重新调用模型，OCR读取缓存，不应称为全新OCR端到端实测。

私有清单、逐页输出、运行日志及逐字段分数保存在仓库外work/preliminary-private/。关键文件为finals-optimization-fixed7.json、finals-v42-fixed7-metrics.json、finals-v47-fixed7-metrics.json和finals-v47-comparison.json，医疗输入及凭据不进入公开Git。

```powershell
python -m scripts.preliminary_kr1 infer --manifest ../preliminary-private/finals-optimization-fixed7.json --config ../local-runtime/private/qianfan-config.json --predictions-dir ../preliminary-private/your-new-predictions --vision --workers 2 --output ../preliminary-private/your-new-run.json
python -m scripts.preliminary_kr1 score --manifest ../preliminary-private/finals-optimization-fixed7.json --predictions-dir ../preliminary-private/your-new-predictions --include-inferred-categories --output ../preliminary-private/your-new-metrics.json
```

默认不设置ZHONGAN_DIRECT_FEE_ROWS。需要有权限访问上述私有文件；仓库本身不含可公开分发的医疗数据。模型调用有随机波动，重跑不保证逐位相同。

## 最终结果

| 指标 | v42基线 | v47默认链路 |
|---|---:|---:|
| 总体F1 | 0.6087 | 0.6783 |
| 费用名称金额F1 | 0.5882 | 0.6667 |
| 费用语义类别复合F1 | 0.5517 | 0.6305 |
| 诊断F1 | 0.8649 | 0.8649 |
| 医院名称F1 | 1.0000 | 1.0000 |
| 完成/部分完成/失败 | 3/4/0 | 4/3/0 |
| 逐页耗时中位数，秒 | 31.984 | 34.844 |
| 逐页耗时总和，秒 | 526.547 | 375.249 |

最终TP=156、FP=77、FN=71，参考原子227。类别评分同时绑定名称、金额和类别，不能把其上升全部归因于分类器改善。耗时总和不是两并发下的墙钟时间，中位耗时也没有改善；只有一次配对运行，不能承诺吞吐提升。缺失原子计数为0，但仍有错误及部分完成，不代表官方五类关键字段缺失率达标。

| 固定页序号 | 基线F1 | 最终F1 |
|---|---:|---:|
| 1，倾斜费用单 | 0.7826 | 0.9565 |
| 2，密集费用单 | 0.4933 | 0.6267 |
| 3，表格恢复材料 | 0.7805 | 0.8293 |
| 4，复杂费用单 | 0.4818 | 0.4818 |
| 5，临床材料 | 0.9412 | 0.9412 |
| 6，临床材料 | 0.5000 | 0.5000 |
| 7，临床材料 | 0.9167 | 0.9167 |

## 被否定的实验与剩余问题

第一版局部复核仍以多行整宽图片输入，出现相邻名称对调；随后改为异常名称单元格独立裁剪，保留原始OCR及修正证据。倾斜页最终名称金额F1达到1.0，仍有一条语义类别与金标不一致。

直接按高置信OCR单元格转录的v46实验总体F1为0.5130；密集页F1下降到0.1467。OCR引擎对明显错误文字也可给100分，绕过模型会压制原有纠错机会。因此该实验默认关闭，保留显式开关及运行配置追踪，不能作为准确率优化宣传。

剩余三页部分完成包含低字段置信度和无法确认行列绑定；原始错金额仍受字面单元格校验约束，尚无独立视觉金额纠错证据。临床材料还存在原文顿号改分号等精确转录差异，不能通过放宽评分器掩盖。下一阶段优先处理金额单元格独立复核、低质量表格重新识别及原文转录保真，然后扩大固定回归范围。

既有完整单元套件527项，66项跳过，其余461项通过；没有新增或修改测试。三项实现分PR提交，未在本轮自动合并或部署。
