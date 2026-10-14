# 火山引擎 OCR 测试接入

2026-10-14，使用部署服务器现有腾讯凭证对程序生成的合成图片调用一次 GeneralAccurateOCR，实际返回 `ResourceUnavailable.ResourcePackageRunOut`。这证明对应 OCR 资源包耗尽，不能据此推断腾讯云账户欠费或其他接口的资源包余额。现有 Worker 把大小写混合的供应方错误码降级成 `PARSE_FAILED`，本次修正为保留格式受控的 OCR 错误码。

火山测试使用 [通用文字识别 OCRNormal](https://www.volcengine.com/docs/86081/1660261?lang=en)，版本 `2020-08-26`，服务 `cv`、区域 `cn-north-1`，通过 HTTPS 提交图片 Base64 表单。需要已开通此能力的火山 IAM AK/SK。联网搜索、方舟和 AI MediaKit 的 API Key 与此接口的鉴权方式不同。免费权益和服务状态以当前账号控制台为准；本改造不调整账号计费设置。

## 本机合成测试

在被 Git 忽略的 `.secrets/volcengine-ocr.env` 填写：

```dotenv
ZHONGAN_OCR_PROVIDER=volcengine
VOLCENGINE_OCR_ACCESS_KEY_ID=<AccessKeyID>
VOLCENGINE_OCR_SECRET_ACCESS_KEY=<SecretAccessKey>
VOLCENGINE_OCR_SECURITY_TOKEN=
```

长期密钥的 Security Token 留空；临时凭证须填写对应 Token。凭证不发到聊天、不提交 Git。可在火山[访问控制控制台](https://console.volcengine.com/iam)的“资源管理 → 密钥管理”查看自己的已有密钥。

项目根目录运行：

```powershell
python -m scripts.probe_ocr --config .secrets/volcengine-ocr.env --output output_dir/volcengine-ocr-probe.json
```

脚本只上传一张内存生成的英文合成测试图片，确认识别到 OCR 与 123.00，输出状态、行数、坐标/置信度数量、请求 ID 和耗时。不会使用业务资料、运行模型分析或修改数据库。网络超时及供应方失败不自动重试，避免重复消耗额度。`passed` 只证明这张图片连通且识别到指定文字，不能代表中文病历、手写体或医疗票据准确率。

## 应用切换

`ZHONGAN_OCR_PROVIDER` 支持 `tencent`、`volcengine`，默认仍是 `tencent`。Worker 和上传预检共用同一选择工厂；失败时不会自动回退到另一家。部署模板允许从服务器 `/home/ubuntu/.config/zhongan/ocr.env` 注入选择和火山凭证，文件应归运行用户所有且权限 `600`。配置生效需发布对应代码并重启 API 和 Worker。本机修改不是服务器已经切换。

OCR 页、文字块和证据保存实际供应方的方法与解析版本。火山返回的 `line_rects` 转换为图片相对坐标；`line_probs` 仅接受有限的 0–1 值，未返回时保持未知，不虚构置信度。接口端设置 `filter_thresh=0` 保留低置信度行供审计，应用继续排除分数低于 0.8 的行，防止不可靠金额进入事实与报告。扫描 PDF 仍由现有流程逐页渲染后识别，避免直接提交多页 PDF 时只识别首页。

## 验证记录

```powershell
python -m unittest discover -s tests -p test_ocr_providers.py -v
python -m unittest discover -s tests -p test_frontend_kr_contracts.py -v
python -m unittest discover -s tests -p test_worker.py -v
```

上述 26 项离线测试通过，覆盖显式切换、缺凭证、失败不回退、表单签名字段、禁止重定向、大小限制、受控错误、缺失置信度、低置信度金额剔除、证据字符位置与两种供应方的方法归因。

2026-10-14，填入用户已有 AK/SK 后，本机真实请求通过：指定合成文字匹配，两行均返回坐标与 0–1 置信度，耗时约 0.58 秒。摘要保存在 `output_dir/volcengine-ocr-probe.json`，不包含凭证、图片或返回全文。
