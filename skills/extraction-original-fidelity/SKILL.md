---
name: extraction-original-fidelity
description: 转录医疗费用名称时保留原文，并把规范名、规格和编码作为独立派生信息。
---

detailName逐字保留原图名称单元格，包括前缀符号、浓度、包装规格、括号、型号和内嵌编号，合并同一单元格的换行；不包含独立编码列或独立规格列。
raw_detail_name保存同一完整原文。normalized_detail_name才用于项目本体名；specification、source_billing_codes为可选派生字段，不回写或替换detailName。
不得按常识补齐截断名称，不纠正原文自身错字。难以区分列边界时保留原文、标记待复核。
evidence_quote保留实际行的名称、数量、单价、金额，不从非相邻位置拼造证据。
