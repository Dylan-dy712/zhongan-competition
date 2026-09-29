# ADR-002 LLM 供应商：OpenAI 兼容协议多供应商适配，原型用智谱 glm-4.5-flash

日期：2026-09-29 · 状态：已接受

## 背景

需要中文医疗语境的生成能力（温度指引）。可用性实测（2026-09-29）：

| 供应商 | 实测结果 |
| --- | --- |
| DeepSeek（flash，支持图像） | key 余额不足（402） |
| 智谱 glm-4.5-flash / glm-4-flash | ✅ 可用；glm-5.3 系列无资源包（429/1113） |
| 本地 Ollama | 安装通道（winget/GitHub）网络不通 |

## 决策

适配器面向 OpenAI 兼容协议（`app/adapters/llm.py`），供应商差异收敛为 base_url/model/thinking 三元组（config 预置）。原型默认 `zhipu + glm-4.5-flash`（thinking=disabled，内容直出）。

要点：
- JSON 稳健抽取（围栏剥离+首个平衡对象），有界重试，usage 记录（成本可核算）；
- MockLLM 确定性降级，调用方必须标记 execution_mode=mock，前端明示"模板模式"；
- 切换供应商 = 改 `services/api/.env` 三行，无需改代码。

## 后果

- 5.3 系列开通资源包后可无缝升级（用户已表达偏好 5.3f）；
- 视觉能力（DeepSeek-flash / 智谱 GLM-4V 系）暂未启用，OCR 以本地 RapidOCR 为主——生产可增加"视觉 LLM 复核低置信页"作为质量增强层。
