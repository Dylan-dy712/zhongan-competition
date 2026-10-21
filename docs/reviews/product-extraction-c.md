# 产品 C 抽取接入

## 链路

设置 `ZHONGAN_DOCUMENT_EXTRACTION=C` 后，Worker 对图片及 PDF 渲染页先使用独立配置的视觉模型判断版式和朝向，再调用 PP-OCRv6 medium GPU/max960，随后调用 document_fields.extract_document 的 C 策略。逐页字段、费用、证据、置信度及复核记录进入页面 metadata 和 model_extractions 审计记录。病例字段适配为现有事实结构，完整 C 字段作为报告上下文；痛点沿用当前证据与知识约束，不额外用旧抽取模型覆盖 C 的首稿。

原生纯文本保持原有路径。图片/PDF 页使用逐页 C，不能把文字材料的旧抽取版本标为 C。已准备的评委样例 OCR/模型缓存不替代真实 C 调用；C 缓存按版本、模型和 OCR 区分。旧的 OCR 低分门控保留，视觉转录单独标记来源和待复核，不作为 OCR 原文伪装入库；没有字段框时只提供整页框，不能声称精确定位。报告审核/发布门槛保留。

密集费用页可能超过五分钟，独立连接每 30 秒续租当前 run，仍要求原 lease_token 和 running 状态。部署包携带运行时 skills；不新增测试代码。

## 配置

API/Worker 从 `/home/ubuntu/.config/zhongan/document-extraction.env` 读取独立配置：

- ZHONGAN_DOCUMENT_EXTRACTION=C
- ZHONGAN_DOCUMENT_LLM_PROVIDER=qianfan
- ZHONGAN_DOCUMENT_LLM_BASE_URL、ZHONGAN_DOCUMENT_LLM_API_KEY、ZHONGAN_DOCUMENT_LLM_MODEL_ID（沿用本机私有千帆配置，密钥不入库）
- ZHONGAN_OCR_PROVIDER=paddle
- ZHONGAN_PADDLE_OCR_MODEL=v6_medium
- ZHONGAN_PADDLE_OCR_DEVICE=gpu:0
- ZHONGAN_PADDLE_OCR_DET_LIMIT=960
- ZHONGAN_PADDLE_OCR_URL=http://127.0.0.1:18869

云服务器无 GPU。本次体验使用本机 8869 的 GPU OCR 服务，通过 SSH 反向转发到云端 127.0.0.1:18869，仅回环可用。必须保持本机开机、OCR 服务和 SSH 转发运行；这不是云端独立 GPU 部署。独立模型配置不覆盖普通对话模型配置。

## 实际验证

本机通过真实 Worker ocr_page 处理一张明确标记为虚构的肺炎出院/费用演示图片，约 32 秒，返回 C 策略、glm-5.3-flash、PP-OCRv6 medium GPU960，以及诊断/药物/天数/费用等字段。使用这次真实输出检查事实适配：保留诊断、药物、5 天住院及 450 元总费用，费用分类/支付汇总均有原文支持；没有为凑总额计算未见项目。数据和凭据保留在仓库外。公网端到端状态以随后部署与实际上传记录为准，不能把本机页级成功当作公网完整成功。
