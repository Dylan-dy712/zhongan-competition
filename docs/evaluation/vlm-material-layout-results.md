# 前置 VLM 布局识别与 PP OCR：实际标注对照

本实验依赖 PR #173 的费用行序与编码分离改动。实现用户提出的“先判断材料模板，再进行 OCR，最后由 VLM 处理疑难字段”，当前接入离线评测链路，尚未接入线上上传入口。没有更换金标、计分器或按结果排除页面。

## 实现范围

1. `material_layout.py` 仅看原图，输出六类材料家族、阅读朝向、可见表头角色、名称是否混有编码/规格。不会输出患者事实或金额，不以机构名称硬编码模板。
2. 朝向自报置信度达到 0.9 时采用旋转角度，交给原有 PP-OCRv6 medium GPU960；否则保留旧方向并记录待复核。自报置信度尚未校准。
3. PP OCR 本身没有语言提示词，也未重新训练。本轮模板规范具体用于图像朝向、向最后的 VLM 提供字段角色，以及有条件地拆分名称、编码和规格。
4. 最终 GLM-5.3-Flash 同时读取原图、bbox 排序后的 OCR 与布局假设，原图/OCR 证据优先于布局假设。混排页面保留 `raw_detail_name`、`specification`、`source_billing_codes` 和原行引用；不确定时保留原名并降低置信度。
5. 检测到费用表但返回零行时记为部分完成，避免只凭调用成功宣称完成。

## 固定口径

共 17 页、13 个病例、823 个评分原子，修订金标 v3；其中旧开发集 7 页、新增对照 10 页。新增页在本轮推理前固定，按清单顺序每个新病例取一张符合费用标注数量条件的页面，并排除旧病例。它们仍属于开发对照，不能称为独立盲测。

计分沿用 `document-fee-taxonomy-exact-v5`：名称金额配对与名称金额类别复合分别计数，按多重集合精确匹配计算 micro F1。未标注字段不计分。当前诊断、手术、用药等五类 KR1 字段尚未完整独立标注，因此这些结果不能直接代表官方完整 KR1 达标。

v55 是上一阶段全部 17 页的真实模型输出；v56 完整重跑前置布局、PP OCR 与最终模型；v57 复用已冻结的同一份真实布局和 OCR，仅重新调用全部页面的最终模型。没有使用 Mock 计分，也没有用已知答案回填抽取结果。不校验原图哈希，不编写或主动运行测试。

## 结果

| 版本 | 旧 7 页 F1 | 新增 10 页 F1 | 全部 17 页 F1 | TP / FP / FN |
| --- | ---: | ---: | ---: | --- |
| v55：费用行序与编码分离 | 0.724512 | 0.713805 | 0.716798 | 591 / 235 / 232 |
| v56：前置布局与朝向驱动 OCR | 0.732456 | 0.862910 | 0.826748 | 680 / 142 / 143 |
| v57：混排页面显式名称分解契约 | 0.748268 | 0.870152 | 0.837554 | 678 / 118 / 145 |

v56 名称金额配对 F1 为 0.848249，类别复合 F1 为 0.797403，17 页均完成。评分器的整字段组缺失率为 0.243%；它不等于逐行漏项率，仍有 143 个 FN。

v57 的 17 页也全部完成，无失败、部分完成或进行中页面；精确率 0.851759、召回率 0.823815，名称金额配对 F1 为 **0.853755**，类别复合 F1 为 **0.815303**。整字段组缺失率为 0.365%，仍有 145 个 FN。总体 F1 较 v55 增加 0.120756，尚未达到 0.90。

以下按冻结清单原顺序列出全部页面，不只展示改善的页面。第 1–7 页为旧开发页，第 8–17 页为扩展页：

| 页序 | v55 F1 | v56 F1 | v57 F1 |
| --- | ---: | ---: | ---: |
| 1 | 0.956522 | 0.956522 | 0.956522 |
| 2 | 0.786667 | 0.786667 | 0.813333 |
| 3 | 0.780488 | 0.829268 | 0.780488 |
| 4 | 0.492754 | 0.484848 | 0.490909 |
| 5 | 0.941176 | 0.941176 | 0.941176 |
| 6 | 0.500000 | 0.400000 | 0.500000 |
| 7 | 0.916667 | 0.916667 | 0.916667 |
| 8 | 0.975000 | 0.975000 | 1.000000 |
| 9 | 0.590164 | 0.836066 | 0.566667 |
| 10 | 0.935897 | 0.935897 | 0.935897 |
| 11 | 0.450980 | 0.450980 | 0.803922 |
| 12 | 0.984127 | 0.984127 | 0.984127 |
| 13 | 0.895238 | 0.895238 | 0.895238 |
| 14 | 0.764706 | 0.882353 | 0.882353 |
| 15 | 0.153846 | 0.877551 | 0.882051 |
| 16 | 0.880952 | 0.880952 | 0.880952 |
| 17 | 0.850299 | 0.862275 | 0.862275 |

### 关键页面观察

- 前置布局 17/17 成功，判为费用清单 14 页、临床材料 3 页；两张原先角度为 0 的横置页改为逆时针 90 度，原先一张 180 度页保持 180 度。未据此声称分类准确率达到 100%。
- 原生 PP OCR 17/17 成功，单页耗时中位数 1.375 秒；布局判断中位数 7.968 秒。
- 横置难页：v55 F1 0.153846 → v56 0.877551；最终抽取耗时 568.250 → 120.453 秒，另有布局 12.938 秒、PP OCR 2.469 秒。这是一次实际观测，不是普遍耗时保证。
- 另一横置页：v55 F1 0.764706 → v56/v57 均为 0.882353。
- 名称/编码/型号混排页：v56 虽拆出编码，仍将部分型号留在名称内，F1 0.450980。v57 只对冻结布局标记为混排的页面要求显式返回原名、规格与编码；先对该条件命中的唯一页面实测，F1 达 0.843137，TP/FP/FN 为 43/8/8，25 行均返回原名、14 行返回非空规格。没有按分数选择此条件。随后全量新调用时，该页 F1 为 0.803922，说明同一提示词仍有波动。
- 第 9 页 v56 达 0.836066，v57 却回落到 0.566667，不能把前一轮涨幅作为稳定能力。v57 横置难页达到 0.882051，最终抽取 90.391 秒。
- v55/v56/v57 最终抽取单页耗时中位数分别为 71.500 / 78.860 / 69.953 秒。各页耗时之和分别为 1732.017 / 1334.953 / 1325.361 秒；这是并发任务的组件耗时总和，不是整批墙钟耗时，也不包含前置布局和原生 OCR。

## 复现

所有原图、金标、配置和输出留在仓库外的私有目录。以下命令在仓库根目录运行，使用已有 API Python 环境、可用 Qianfan GLM-5.3-Flash 和已启动的 PP-OCRv6 medium GPU960 服务；不把私有配置加入 Git。

```powershell
$py = '..\venv-care-quality\Scripts\python.exe'
$private = '..\preliminary-private'
$config = '..\local-runtime\private\qianfan-config.json'
& $py -m scripts.preliminary_layout --manifest "$private\fee-row-fixed17.json" --config $config --output-root "$private\layout-repro-plans17" --output "$private\layout-repro-planned17.json" --workers 2
& $py -m scripts.preliminary_ocr --provider paddle --manifest "$private\layout-repro-planned17.json" --config "$private\paddle-v6-960-runtime.json" --output-root "$private\layout-repro-ocr17" --workers 1
```

以下步骤只更新 OCR 文件路径与内容指纹，保留原图、参考答案、页面顺序、布局与朝向字段；不校验原图哈希，也不重新挑页：

```powershell
@'
from pathlib import Path
from scripts.preliminary_kr1 import load, sha, write
private = Path('../preliminary-private')
manifest = load(private / 'layout-repro-planned17.json')
for row in manifest['documents']:
    cache = private / 'layout-repro-ocr17' / row['case_id'] / (Path(row['image']).stem + '.json')
    row['ocr'] = str(cache.resolve())
    row['ocr_sha256'] = sha(cache)
    row['ocr_source_status'] = load(cache)['ocr_status']
write(private / 'layout-repro-frozen17.json', manifest)
'@ | & $py -
```

随后运行：

```powershell
& $py -m scripts.preliminary_kr1 infer --manifest "$private\layout-repro-frozen17.json" --config $config --predictions-dir "$private\layout-repro-predictions17" --output "$private\layout-repro-run17.json" --vision --ocr-layout bbox --workers 2
& $py -m scripts.preliminary_kr1 score --manifest "$private\layout-repro-frozen17.json" --predictions-dir "$private\layout-repro-predictions17" --output "$private\layout-repro-metrics17.json" --include-inferred-categories
```

实际冻结文件为 `vlm-layout-v1-planned17.json`、`vlm-layout-v1-v6-frozen17.json`，布局输出为 `vlm-layout-v1-plans17/`，原生 OCR 为 `vlm-layout-v1-v6-ocr17/`。最终预测和指标分别使用 `vlm-layout-v56-*`、`vlm-layout-v57-*` 前缀。在线模型重跑会有波动，不能承诺逐字一致。

v57 的预测目录为 `vlm-layout-v57-predictions17/`，运行状态为 `vlm-layout-v57-run17.json`，三个指标文件为 `vlm-layout-v57-metrics7.json`、`vlm-layout-v57-metrics10.json`、`vlm-layout-v57-metrics17.json`。最后一项回退标记修复只使不确定布局的 `orientation_review_required` 与布局记录一致；已冻结的 17 页均为明确采用方向，不受该修复影响。

## 结论与边界

当前最明确的改善来自正文朝向纠正与混排字段边界。两者组成的方案有继续保留的价值；现有单轮结果不能分离每个因素的独立贡献，也不能证明泛化稳定性。仍需处理项目名修饰词、规格边界与费用语义类别，不能宣称已经完美达到 KR1 F1 0.90。
