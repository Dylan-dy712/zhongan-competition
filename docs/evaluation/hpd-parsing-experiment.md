# HPD-Parsing：最新模型配对实验

## 目标与固定条件

在 PP-OCRv5 GPU 960 已有七页 F1 0.7217 的基础上，实跑官方更新发布的 HPD-Parsing，不因发布日期推断效果。

继续使用 `../preliminary-private/finals-optimization-fixed7.json` 全部七页、同一 revised-v3 金标和 `document-fee-taxonomy-exact-v5` 评分器。后续 GLM-5.3-Flash、v48 prompt、vision 开启、bbox 参数、两并发及费用类别计分口径保持一致。七页是开发材料，非独立或官方测试集。保留失败页，禁止以视觉抽取绕过失败 OCR。

## 运行路线

官方 2026-07-22 公告发布 HPD-Parsing。高吞吐部署使用定制 vLLM，要求 Linux 或 Linux GPU 容器以及支持 CUDA 12.8 的驱动。本机 Windows / RTX4060 Laptop 8GiB / 驱动566.07支持到CUDA12.7，所以本轮采用模型仓库提供的 **Transformers参考实现**，不是 vLLM 吞吐测评，也不更新驱动。

- 原生依赖安装在仓库外 `../hpd-parsing-local/.venv`，不影响 API 或 Paddle 环境。
- 官方模型来源 `PaddlePaddle/HPD-Parsing`，本机经 ModelScope 同名官方仓库下载；下载文件清单和版本保存在私密目录，权重与发布的模型 SHA256 对照。这不是原图哈希检查。
- 使用官方 `image_preprocess.py` 的动态切片（最多24格加缩略图）、BF16、`generate_hpd`、P-MTP 6、子分支串行复用缓存、每分支最多8000新token，固定提示词 `document parsing with fork.`。
- 原图仅应用清单已固定的方向；不额外根据金标决定裁剪或旋转。
- 保留完整原始结构文本给既有抽取器，包括表格内容。不编造单元格坐标或字段置信度；`lines=[]` 时 bbox 处理沿用既有文本回退。
- 不自动切换应用默认 OCR。是否选用由实际完成率与金标结果决定。

## 复现命令

先按 `services/api/requirements-hpd-experiment.txt` 在独立 Python3.11 环境安装依赖，下载完整官方模型及 Python 架构文件。自定义代码随模型运行，应固定并记录版本；不要只下载权重。所有输入输出均在Git仓库外。

```powershell
../hpd-parsing-local/.venv/Scripts/python.exe -m scripts.hpd_parsing_experiment --model-root ../hpd-parsing-local/model --manifest ../preliminary-private/finals-optimization-fixed7.json --output-root ../preliminary-private/hpd-frozen7-ocr --output-manifest ../preliminary-private/hpd-frozen7.json
../venv-care-quality/Scripts/python.exe -m scripts.preliminary_kr1 infer --manifest ../preliminary-private/hpd-frozen7.json --config ../local-runtime/private/config.json --predictions-dir ../preliminary-private/hpd-v48-frozen7-predictions --output ../preliminary-private/hpd-v48-frozen7-run.json --vision --ocr-layout bbox --workers 2
../venv-care-quality/Scripts/python.exe -m scripts.preliminary_kr1 score --manifest ../preliminary-private/hpd-frozen7.json --predictions-dir ../preliminary-private/hpd-v48-frozen7-predictions --output ../preliminary-private/hpd-v48-frozen7-metrics.json --include-inferred-categories
```

只对完整七页清单评分；运行中间的部分清单不是最终结果。重新运行请使用新输出目录。原始结构、逐页耗时、切片数、GPU峰值分配、错误及运行环境均留在私密产物中。每分支8000token预算仍有截断风险，不能仅凭非空输出判断内容完整。

本轮不新增或运行测试，用真实原图推理与现有标注比较。

来源：[官方公告](https://github.com/PaddlePaddle/PaddleOCR#-recent-updates)、[部署要求](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/HPD-Parsing.html)、[官方模型与Transformers实现](https://huggingface.co/PaddlePaddle/HPD-Parsing)。
