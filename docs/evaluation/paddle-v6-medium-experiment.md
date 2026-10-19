# PP-OCRv6 medium 配对实测协议

## 运行前固定

沿用`finals-optimization-fixed7.json`相同七页开发材料、原图、方向及修订金标v3，共227个评分原子。全部页保留，不按本轮分数筛选，不校验原图哈希，不更改金标或计分器。

仅改变OCR模型与事先声明的分辨率配置；不启用表格结构模型，不新增图像增强、自动方向、文字行旋转或去畸变。沿用清单已有方向。两组新鲜OCR：

| 组 | 检测/识别模型 | 检测分辨率 |
|---|---|---|
| v6-960 | PP-OCRv6_medium_det＋medium_rec | 与v5对齐：最长边960 |
| v6-default | 相同medium模型 | 官方管线默认：最短边64，最大边4000 |

基线复用上一轮v50的PP v5 GPU960七页结果（`hybrid-v50-control7-*`，F1 0.7115），明确不是本轮重新调用基线模型。新旧组的GLM-5.3-Flash、v50提示词、vision开启、bbox布局、两并发、direct-fee关闭和费用分类计分均一致；对比前核对保存的抽取实现摘要。

主指标为全部页总体F1、名称金额配对和类别复合F1、完整/部分/失败数。附带原生OCR耗时、行数、金标费用名称字面命中；后者不能当作全文OCR准确率或CER。没有逐字全文金标，不报告纯OCR准确率。

## 部署

复用隔离的`paddleocr-gpu-local/.venv`（Paddle3.2.2 CUDA12.6、PaddleOCR3.7.0/PaddleX3.7.2），仅在独立目录`paddleocr-v6-local/models/`下载官方medium检测/识别模型。记录来源、文件大小和归档SHA作为模型版本信息，不涉及原图哈希。

侧车参数`--ocr-model v6_medium`，API选择对应配置`ZHONGAN_PADDLE_OCR_MODEL=v6_medium`。v5仍为默认；v6每个配置有独立parser版本、方法与缓存。服务和客户端必须版本一致，失败不回退到腾讯或v5。

```powershell
# GPU环境启动960控制配置；默认分辨率组改为--det-limit 64、--port 8870
python -m scripts.paddle_ocr_service --model-root ../paddleocr-v6-local/models --device gpu:0 --ocr-model v6_medium --det-limit 960 --port 8869

# config仅含该侧车的本地参数，不含模型密钥
python -m scripts.preliminary_ocr --provider paddle --manifest ../preliminary-private/finals-optimization-fixed7.json --config ../preliminary-private/paddle-v6-960-runtime.json --output-root ../preliminary-private/paddle-v6-960-ocr7 --workers 1
```

OCR完成后生成对应新清单，仅替换缓存路径及缓存摘要，保持同一图像、方向、文档与参考。后续使用专门GLM配置`../local-runtime/private/qianfan-config.json`，不能替换为应用的DeepSeek默认配置：

```powershell
python -m scripts.preliminary_kr1 infer --manifest ../preliminary-private/paddle-v6-960-frozen7.json --config ../local-runtime/private/qianfan-config.json --predictions-dir ../preliminary-private/paddle-v6-960-v50-predictions --output ../preliminary-private/paddle-v6-960-v50-run.json --vision --ocr-layout bbox --workers 2
python -m scripts.preliminary_kr1 score --manifest ../preliminary-private/paddle-v6-960-frozen7.json --predictions-dir ../preliminary-private/paddle-v6-960-v50-predictions --output ../preliminary-private/paddle-v6-960-v50-metrics.json --include-inferred-categories
```

64配置使用相应独立路径。所有医疗原图、缓存、预测、私密配置、权重与原生依赖留在Git仓库外；重新推理使用新输出目录。

本轮不写或主动运行测试。验证来自实际OCR、真实GLM调用及金标评分。七页是开发材料，不代表全量、独立或官方KR1达标。未据实测结果决定前不改变应用默认配置，不部署公网。

来源：[官方OCR使用说明](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html)；同时核对了本机PaddleX3.7.2的OCR管线默认配置。

[最终结果](paddle-v6-medium-results.md)：v6-960 F1为0.7332，原v5基线0.7115；默认分辨率3/7成功、全部计入后F1为0.5278。没有自动切换应用默认模型。
