# 腾讯 OCR → PaddleOCR：接入与配对实验

## 固定设计（运行前登记）

目标是将PaddleOCR接入API与Worker共用的OCR工厂，并对比替换前后的实际金标结果，不以模型名称、字符数量或软件测试通过率判断优劣。

沿用改动前已冻结的七页材料：一页倾斜费用单、三页既有表格恢复材料、前三页临床范围材料，含一页预先冻结180度方向。所有页保留，不按得分替换样本。金标、评分器、GLM-5.3-Flash、vision开启、bbox行重建、两并发抽取均相同。不开启直接转录实验，不校验原图哈希。

对照A：现有腾讯缓存，包含已得到的表格V3结构；重新调用GLM抽取。对照B：同一原图新鲜调用PP-OCRv5 server检测与识别，重新调用同一GLM。这是完整替换策略的对比，不能把差异全部归因于纯文字识别，因为腾讯组有结构化表格而PP组当前没有表格结构模型。腾讯组为缓存，不冒充两组都新鲜OCR。

主指标为相同金标下总体F1、名称金额配对F1、类别复合F1、临床字段F1、完成/部分完成/失败数。类别复合指标同时依赖名称与金额。辅助指标为金标费用名称的OCR字面命中数，以及OCR耗时、模型抽取耗时。字面命中不是CER、不是费用行金额F1。未独立标注完整OCR文字，不能声称全文OCR准确率。

这是已接触开发材料的配对回归，不是独立测试集，不能外推为全量或官方KR1达标。固定模型也存在调用波动。

正式配对抽取版本固定为v48。接入时发现旧版大尺寸、无结构化表格的费用视觉分支没有传入OCR文字，v48补充该上下文，两组均按此版重跑。之前v47单页及前三页进度只用于诊断，不替代最终七页分数。

## 工程实现

Paddle运行在独立Python 3.11 CPU环境，服务仅监听127.0.0.1:8866；API通过ZHONGAN_OCR_PROVIDER=paddle选择它，使用ZHONGAN_PADDLE_OCR_URL指定本机地址。API进程不导入Paddle原生库，侧车通过常驻子进程加载一次模型并串行推理，关闭请求正文和识别正文日志。PP失败明确报错，不回退到腾讯。工厂保留既有供应商选项以兼容其他部署，本机私密运行配置已显式选择paddle，并关闭腾讯表格二次调用。

实跑第4页出现600秒HTTP超时且原生调用未返回。修复后原生子进程有300秒单页预算，超时返回504并终止该子进程，下页重新加载模型；原生崩溃也可重建。不能靠HTTP超时本身取消Paddle调用。前三页既有输出均在300秒内，保留使用；超时页明确计入失败数。health同时提供busy和native_worker_ready，不把服务存活当成效果达标。

版本为PaddleOCR 3.7.0 / PaddleX 3.7.2 / PaddlePaddle 3.2.2 / NumPy 1.26.4，PP-OCRv5_server_det与server_rec。复用已下载模型，不向API依赖环境安装Paddle。最长检测边960、4线程、MKLDNN关闭，是本机此前实际运行成功的配置；不能承诺是效果最优参数。模型不含表格结构恢复，不自动纠偏或旋转；可使用已有流程明确给定的方向，并将坐标映射回原图。

```powershell
# 在独立Paddle环境安装，或复用已有paddleocr-local/.venv
python -m pip install -r services/api/requirements-paddle.txt
python -m scripts.paddle_ocr_service --model-root ../paddleocr-local/model-cache/official_models

# API和Worker启动前设置；服务必须已ready
$env:ZHONGAN_OCR_PROVIDER='paddle'
$env:ZHONGAN_PADDLE_OCR_URL='http://127.0.0.1:8866'
$env:ZHONGAN_TABLE_OCR='0'

# 所有医疗缓存、运行输出保留在Git仓库外
python -m scripts.preliminary_ocr --provider paddle --manifest ../preliminary-private/finals-optimization-fixed7.json --output-root ../preliminary-private/paddle-migration-ocr7 --workers 1
```

随后只替换清单内OCR路径和对应OCR摘要，保留相同document_id、原图、方向、参考及参考摘要。两组分别调用preliminary_kr1 infer --vision --ocr-layout bbox及score --include-inferred-categories。版本、配置与结果一起记录；新增输出目录避免复用旧预测。

本轮不新增、修改或主动运行测试，只比较实际识别、抽取结果与标注。替换本机运行配置不代表公网已部署。
