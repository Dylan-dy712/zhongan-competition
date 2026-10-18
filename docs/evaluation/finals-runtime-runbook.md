# P0：决赛运行预检与恢复

本PR依赖前三项P0及#95。新增代码不包含医疗输入、密钥、生产环境配置或模型权重；不自动部署，不购买资源包。

## 运行前检查

```powershell
python -m scripts.finals_preflight --config ../private/ocr.json --config ../private/model.json --manifest ../private/manifest.json --output ../private/preflight-static.json
```

默认只检查依赖、凭据存在性、输入映射、OCR/参考版本；不代表额度可用。输出不含凭据和医疗正文，不验证原图哈希。新数据尚无标注时允许reference缺失，但不能报告F1。

```powershell
python -m scripts.finals_preflight --config ../private/ocr.json --config ../private/model.json --ocr-provider tencent_table --live --table --output ../private/preflight-live.json
```

`--live`对本地生成的无患者信息图片及简单JSON请求执行实际OCR/模型调用，可能消耗额度；仅全部通过才标ready_for_rehearsal。表格主模式必须显式选择，不静默改收费API；此预检只证明服务可用，不证明新病历效果或全部链路通过。

2026-10-18实际结果：通用腾讯OCR返回ResourceUnavailable.ResourcePackageRunOut；表格V3和千帆glm-5.3-flash可用。显式tencent_table模式的主OCR、表格、模型三个探针均通过。凭据保存在本地私密文件，不在此文档中。

## 冻结与新鲜运行

先固定代码提交和输入清单，所有输出放仓库外；医疗原图不进公开Git。

```powershell
python -m scripts.preliminary_ocr --manifest ../private/input.json --config ../private/ocr.json --output-root ../private/fresh-table --table --workers 1
```

随后建立新的运行清单，将OCR路径与OCR版本摘要指向新缓存，保留document_id及参考版本。不得把旧缓存写成新鲜识别。

```powershell
python -m scripts.preliminary_kr1 infer --manifest ../private/frozen-run.json --config ../private/model.json --predictions-dir ../private/predictions --vision --workers 2 --output ../private/run.json
python -m scripts.preliminary_kr1 score --manifest ../private/frozen-run.json --predictions-dir ../private/predictions --include-inferred-categories --output ../private/metrics.json
```

## 中断及部分失败

同一预测目录仅允许一个运行进程。相同命令续跑跳过已完成项，继续失败或中断项。`--retry-partial`显式重跑部分完成项；要求模型、实现、OCR、方向及运行模式相同，变更时必须使用新目录。

检查点包含旧部分结果的恢复快照；重试失败时保留较完整的已验证部分，不按参考答案选择结果、不把新旧字段自由拼接。完成与部分完成分别统计，缺失和失败保留分母。HTTP超时是请求级预算，不宣称严格的整次运行硬截止。

实现摘要新增路由、行绑定与逐行证据模块，避免辅助模块变更后误复用旧预测。

验证：31项相关既有检查通过，未新增或修改测试；配置检查、三页输入预检以及无患者信息的新鲜服务探针已执行。未执行四P0整合后的独立全量评测，不声称达标。

## 演示前放行条件

固定同一版本在未参与本轮调优的病例上跑完，分别报告总体/材料类型/字段指标与失败数；不以精选演示集代替全量。另按最终确认的KR2—KR5要求演练痛点原因、个性化报告、画像解释及反馈链路。出现新鲜识别失败、未批准报告或未完成评分，应如实显示待处理，不返回保存的旧结果冒充现场结果。
