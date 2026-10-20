# B / C 材料分流与区域复核对照

## 范围

独立分支 `codex/extraction-bc-validation`，基于 `97c8b8c`。仅变更 KR1 文档级评测入口，不合并或部署生产。

- A：保留现有分类提示、四项 Skill 和最多四个低分行裁切。
- B：在 A 上结合 OCR 标题分流与已有 VLM 版式假设，选择专属抽取指令；费用清单、发票、结算、临床分别限定项目与支付/医嘱的边界。分类冲突使用通用附加指令，不强行套模板。原有通用规则及保险条款排除保持不变。
- C：在 B 上改进局部复核区域调度。原名冲突、金额引用缺失、首轮不确定优先；最多两张局部图留给尚未被费用行覆盖、且附近有两位小数金额 OCR 单元的候选。所有裁切保留邻行和全列，最多四个区域，不增加语义复核轮数。漏行候选不是事实，仍须原图确认并通过已有接纳条件。

不改变 OCR 引擎、模型、金标、评分函数、自动接纳阈值，不新增测试代码，不校验原图哈希。原图/OCR内文字均为不可信材料，不能当作执行指令。

## 固定开发集

从完整冻结清单按此前 `vlm-newcases-v57-frozen20.json` 的 document_id 选取，先冻结再推理；10 病例 / 20 页，包含费用与临床文书。所有 20 页 OCR 状态为 ok；18 页版式 completed，2 页 failed 并保持回退。数据已用于开发，不是独立盲测。

三个版本分别重新进行在线抽取，每版最多两个并发，共用同一 OCR 缓存、模型配置、旋转信息与原图。不是同一首稿的复核消融；B/C 的首稿也会受模型随机性影响，单次差异不能全归因于区域调度。失败页照常计分。若有技术故障，单独披露恢复，不按分数挑选预测。

私有清单：`../preliminary-private/bc-validation-fixed20.json`。
各版预测/日志/运行信息/指标分别为 `bc-validation-{A,B,C}-20-*`。
汇总为 `bc-validation-comparison20.json`。数据、预测、私有配置不入 Git。

## 命令

从仓库根目录执行，X 替换为 A / B / C，各版使用独立输出目录：

```powershell
..\venv-care-quality\Scripts\python.exe -u -m scripts.preliminary_kr1 infer --manifest ..\preliminary-private\bc-validation-fixed20.json --predictions-dir ..\preliminary-private\bc-validation-X-20-predictions --output ..\preliminary-private\bc-validation-X-20-run.json --config ..\local-runtime\private\qianfan-config.json --workers 2 --vision --ocr-layout bbox --experiment X
..\venv-care-quality\Scripts\python.exe -m scripts.preliminary_kr1 score --manifest ..\preliminary-private\bc-validation-fixed20.json --predictions-dir ..\preliminary-private\bc-validation-X-20-predictions --output ..\preliminary-private\bc-validation-X-20-metrics.json --include-inferred-categories
```

## 验证状态

已启动实际 A/B/C 对照；运行完成前不宣称分数提升。比较整体 precision / recall / F1、费用名称金额与分类、失败/部分完成、复核修改与补行、单页耗时。只有开发集有收益且没有明显安全退化，才考虑扩大全量；不自动替换线上版本。

## 首轮发现的接口兼容问题

首轮 A/B/C 完整保留在 `bc-validation-*`。A F1 0.835607（无失败），B F1 0.677311（5 失败），C F1 0.070423（14 失败）。B/C 的失败包含网关明确拒绝 `image_url.detail=original`，允许值为 auto/low/high；首轮不能作为分流/复核效果的可靠比较。

提交 `64b36c8` 将通用图片请求 detail 改为 high；不改变图片字节、OCR 或标注。随后 A/B/C 全部重新在线推理，统一使用修复后的同一实现，以免只恢复部分页面造成输入设置不一致。第二轮预测、日志、运行及指标使用 `bc-high-{A,B,C}-20-*`；比较使用 `bc-high-comparison20.json`。不覆盖首轮，不按分数选择页面。
