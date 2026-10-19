# HPD-Parsing 实测：保留现有 PP v5 默认方案

## 结果

HPD-Parsing 已在本机 RTX4060 Laptop 8GiB 上通过官方 Transformers 参考实现完成全部七页原图解析。**当前接入方式没有提高最终字段 F1，不切换应用默认方案。**

最终对照统一使用 GLM-5.3-Flash、v49提示词、vision开启、bbox参数、两并发和同一计分器；三组预测文件记录的实现摘要一致。金标仍为同一227个计分原子，没有删除失败或低分页。

| OCR/解析输入 | 总体 F1 | 名称金额配对 F1 | 类别复合 F1 | 诊断 F1 | 最终状态 |
|---|---:|---:|---:|---:|---|
| 腾讯缓存（含V3表格） | 0.6652 | 0.6569 | 0.6108 | 0.8649 | 完成4、部分完成3 |
| **PP-OCRv5 GPU960** | **0.7028** | **0.6961** | **0.6569** | **0.8649** | **完成7** |
| HPD-Parsing Transformers | 0.5640 | 0.5419 | 0.5222 | 0.7179 | 完成7 |

总体TP/FP/FN：腾讯153/80/74，PP v5为162/72/65，HPD为130/104/97。医院字段三组F1均为1.0。

HPD比同轮PP v5低13.88个百分点；不能拿不同模型或不同提示词下的分数拼接成提升。之前v48 GLM下PP v5的0.7217仍保留为历史运行，当前v49同轮为0.7028，LLM调用和提示词变化均可能影响结果。

## 成本与实现边界

HPD七页解析均成功，总耗时167.638秒，单页中位24.484秒，范围13.421–32.906秒；GPU峰值已分配显存7.91GiB。耗时包含逐页预处理及推理，不包含首次加载和后续GLM抽取。此前PP v5七页原生OCR总计5.420秒，计时边界并不完全一致，但本机HPD明显更慢。

HPD使用BF16、官方动态切片（24格上限加缩略图）、P-MTP6、子分支串行复用KV缓存；未安装FlashAttention2，使用官方支持的回退实现。不是定制vLLM吞吐方案，不应套用官方高吞吐基准。权重来自官方同名ModelScope仓库，发布的权重SHA256核对通过，包含7个MTP参数张量。

五页输出包含HTML表格。当前实验将完整结构文本交给既有GLM抽取器，没有把HPD块坐标或HTML转换成腾讯单元格协议，也未对HPD做专门的单元格适配。名称金额配对和诊断指标均下降；尚不能把损失全部归因于纯文字识别。结论只针对这个模型、配置和接入方式。

## 保留的失败与口径修正

首次运行误用应用`config.json`中的DeepSeek Flash，v48总体F1为0.1725（完成3、部分完成3、失败1）；费用阶段三页HTTP400，因为JSON模式要求提示词明确含JSON。该结果保留，但不能与历史GLM结果比较。

v49只在费用转录提示词中增加JSON并更新版本号。DeepSeek三组同版结果另行保留：腾讯0.6109（失败1）、PP v5为0.4696（失败3）、HPD为0.6432（失败1）。失败页没有剔除。这提示端到端结果同时受下游模型及Schema稳定性影响，不能将OCR模型名当成质量保证。

随后使用独立的`qianfan-config.json`，在三组全部重跑同版GLM，得到上面的主表。应用配置、金标和计分器没有改变。

## 复现与证据

运行步骤见[实验协议](hpd-parsing-experiment.md)，固定清单为`finals-optimization-fixed7.json`，HPD缓存清单为`hpd-frozen7.json`。七页输入仍为已接触开发样本，非独立或官方KR1验证。

私密产物均在`../preliminary-private/`：

- `hpd-frozen7-ocr/`：原始结构文本、逐页状态/耗时/显存、模型代码版本。
- `hpd-frozen7-inference.log`：GPU模型运行记录。
- `hpd-v49-glm-frozen7-predictions/`及`-run.json`、`-metrics.json`。
- `paddle-v49-glm-frozen7-*`、`tencent-v49-glm-frozen7-*`：相同口径对照。
- `hpd-final-paired-comparison.json`：汇总与模型/提示词/实现一致性记录。
- 不含`glm`的`*-v49-frozen7-*`：早期DeepSeek对照，独立标识。

当前版本的GLM复现示例（先完成HPD原图解析）：

```powershell
python -m scripts.preliminary_kr1 infer --manifest ../preliminary-private/hpd-frozen7.json --config ../local-runtime/private/qianfan-config.json --predictions-dir ../preliminary-private/hpd-v49-reproduce-predictions --output ../preliminary-private/hpd-v49-reproduce-run.json --vision --ocr-layout bbox --workers 2
python -m scripts.preliminary_kr1 score --manifest ../preliminary-private/hpd-frozen7.json --predictions-dir ../preliminary-private/hpd-v49-reproduce-predictions --output ../preliminary-private/hpd-v49-reproduce-metrics.json --include-inferred-categories
```

没有新增、修改或主动运行测试，没有校验原图哈希。所有效果结论来自真实解析、模型抽取和现有金标比较；没有公网部署或KR1达标声明。
