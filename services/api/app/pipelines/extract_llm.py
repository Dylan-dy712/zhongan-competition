"""B 层：LLM 辅助抽取（规格 §6.1）。

职责边界：
- 只做候选补全（诊断/药品/手术），不改写 A 层结果；与 A 层近似重复的候选丢弃，
  冲突解释权在规则层（确定性优先，spec §4.1）。
- 每个候选必须带 OCR 原文引用（quote），引用锚定失败即丢弃——不允许
  "模型说有"而无原文的证据（规格 §5.3：evidence 存在不代表支持结论，
  这里反向要求：没有 evidence 不许成候选）。
- execution_mode=mock 或 LLM 不可用时静默跳过，facts 保持 A 层原样。

成本：每案 1 次调用（OCR 全文输入 + JSON 输出），glm-4.5-flash 单案 <1 分钱。
"""

from __future__ import annotations

import re

from ..adapters.llm import LLMError, MockLLM
from ..contracts.common import Assertion, Evidence, FieldValue, TextSpan
from ..contracts.facts import DiagnosisItem, MedicationItem, ProcedureItem

PROMPT_VERSION = "extract-llm-0.1.0"

SYSTEM_PROMPT = """你是医疗记录结构化助手。输入是某次理赔材料的多页 OCR 全文（页与行以标记分隔）。
任务：抽取三类候选实体，只允许逐字引用 OCR 中出现的内容：

1. diagnoses：诊断/结论（含门诊诊断、入院/出院诊断、病理诊断、影像结论中的疾病判断）。
   - 病理报告的最终诊断必须抽（格式如"（部位）+ 结论"整体引用）；
   - 排除：检验项目的数值行、生命体征、入院/出院日期、医院科室名、身体部位单独出现（无疾病判断）；
   - 排除：症状与体征描述（如"咳嗽""腹痛"）、检查所见/影像表现原文（"见片状影"不是诊断）；
   - 排除：仅在既往史/婚育史/个人史中被提及、且未出现在任何诊断结论位置的疾病。
2. medications：药品名（含出院带药、门诊处方、用药医嘱中的药品）。
   - 只收"开给患者的药"（处方/医嘱/带药语境），不收费用清单计费行、检查试剂、耗材、敷料；
   - 排除：医疗操作项目名（"静脉输液""换药""雾化吸入"不是药）。
3. procedures：手术与操作名称（含门诊操作，如"骨髓穿刺术"）。
   - 排除：检查（CT/超声/心电）、检验（血常规）。

规则：
- quote 必须是 OCR 原文中连续出现的一段文字（≤60 字），从中能直接看出该实体；
- 只输出 JSON：
{"diagnoses":[{"text":"...","quote":"...","role":"outpatient|admission|discharge|pathology"}],
 "medications":[{"text":"...","quote":"..."}],
 "procedures":[{"text":"...","quote":"..."}]}
- 数量上限：diagnoses 12、medications 12、procedures 6；没有就给空数组；
- 不确定的不要输出。只输出 JSON。"""

_MAX_QUOTE = 60
_STRIP = re.compile(r"[\s，,；;：:、（）()【】\[\].·\-—_#*×xX\d]")


def _norm(s: str) -> str:
    return _STRIP.sub("", s or "")


def _similar(a: str, b: str) -> float:
    import difflib

    x, y = _norm(a), _norm(b)
    if not x or not y:
        return 0.0
    if x in y or y in x:
        return 1.0
    return difflib.SequenceMatcher(None, x, y).ratio()


def _anchor_quote(bundle: dict, quote: str) -> tuple[dict, int] | None:
    """在页 OCR 行中定位 quote：先精确子串，再归一化包含。返回 (page, line_index)。"""
    q = quote.strip()
    if not q:
        return None
    qn = _norm(q)
    if len(qn) < 4:
        return None
    for pg in bundle.get("pages", []):
        for i, ln in enumerate(pg.get("lines", [])):
            t = ln.get("text", "")
            if q in t or (qn and qn in _norm(t)):
                return pg, i
        # quote 可能跨行：归一化整页文本后查找行范围
        lines = pg.get("lines", [])
        joined = _norm("".join(ln.get("text", "") for ln in lines))
        if qn in joined:
            pos = joined.find(qn)
            acc = 0
            for i, ln in enumerate(lines):
                acc += len(_norm(ln.get("text", "")))
                if acc >= pos + len(qn):
                    return pg, i
    return None


# 计费页：药品/诊断出现在费用行不代表处方或临床判断，B 层一律不采纳
_BILL_PAGE_TYPES = {"inpatient_bill", "outpatient_bill", "invoice"}


def _page_is_bill(pg: dict) -> bool:
    return pg.get("classification", {}).get("doc_type") in _BILL_PAGE_TYPES


def enrich_facts(facts, bundle: dict, llm) -> dict:
    """B 层入口：返回 {"status": "skipped|enriched|failed", "added": {...}}。"""
    if isinstance(llm, MockLLM):
        return {"status": "skipped", "reason": "mock"}
    pages_text = "\n\n".join(
        f"<<<第{i+1}页 [{p['classification']['doc_type']}]>>>\n{p.get('text','')}"
        for i, p in enumerate(bundle.get("pages", []))
    )
    if len(pages_text) > 60000:
        pages_text = pages_text[:60000]
    try:
        data = llm.chat_json(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": pages_text}],
            max_tokens=2500,
        )
    except LLMError as exc:
        return {"status": "failed", "reason": str(exc)[:120]}

    existing_dx = [d.name.value or "" for d in facts.diagnoses]
    existing_med = [m.name.value or "" for m in facts.medications]
    existing_proc = [p.name.value or "" for p in facts.procedures]
    added = {"diagnoses": 0, "medications": 0, "procedures": 0}
    dropped_no_anchor = 0
    dropped_bill_page = 0

    def _add_evidence(quote: str, *, exclude_bill: bool = False):
        nonlocal dropped_no_anchor, dropped_bill_page
        hit = _anchor_quote(bundle, quote[:_MAX_QUOTE])
        if not hit:
            dropped_no_anchor += 1
            return None
        pg, li = hit
        if exclude_bill and _page_is_bill(pg):
            dropped_bill_page += 1
            return None
        line_text = pg["lines"][li].get("text", "") if li < len(pg.get("lines", [])) else ""
        return Evidence(
            case_id=facts.case_id, document_id=pg["document_id"], page_index=pg.get("page_index"),
            line_index=li, text_span=TextSpan(start=0, end=len(line_text), text=line_text),
            bbox=pg["lines"][li].get("bbox") if li < len(pg.get("lines", [])) else None,
            extraction_method=f"llm@{getattr(llm, 'model', 'unknown')}",
        )

    enc = facts.encounters[0] if facts.encounters else None
    enc_id = enc.encounter_id if enc else ""

    for item in (data.get("diagnoses") or [])[:12]:
        text = str(item.get("text", "")).strip()
        if not text or len(text) > 30:
            continue
        if any(_similar(text, e) >= 0.75 for e in existing_dx):
            continue
        ev = _add_evidence(str(item.get("quote", "")), exclude_bill=True)
        if ev is None:
            continue
        facts.evidences.append(ev)
        role = str(item.get("role", "discharge"))
        if role not in ("outpatient", "admission", "discharge", "pathology"):
            role = "discharge"
        facts.diagnoses.append(DiagnosisItem(
            encounter_id=enc_id, role=role,
            name=FieldValue.observed(text, ev.text_span.text, [ev.evidence_id], 0.6,
                                     f"{PROMPT_VERSION}@llm"),
            is_primary=False,
        ))
        existing_dx.append(text)
        added["diagnoses"] += 1

    for item in (data.get("medications") or [])[:12]:
        text = str(item.get("text", "")).strip()
        if not text or len(text) > 24:
            continue
        if any(_similar(text, e) >= 0.75 for e in existing_med):
            continue
        ev = _add_evidence(str(item.get("quote", "")), exclude_bill=True)
        if ev is None:
            continue
        facts.evidences.append(ev)
        facts.medications.append(MedicationItem(
            encounter_id=enc_id,
            name=FieldValue.observed(text, ev.text_span.text, [ev.evidence_id], 0.6,
                                     f"{PROMPT_VERSION}@llm"),
            phase="outpatient",
        ))
        existing_med.append(text)
        added["medications"] += 1

    for item in (data.get("procedures") or [])[:6]:
        text = str(item.get("text", "")).strip()
        if not text or len(text) > 26:
            continue
        if any(_similar(text, e) >= 0.75 for e in existing_proc):
            continue
        ev = _add_evidence(str(item.get("quote", "")), exclude_bill=True)
        if ev is None:
            continue
        facts.evidences.append(ev)
        facts.procedures.append(ProcedureItem(
            encounter_id=enc_id,
            name=FieldValue.observed(text, ev.text_span.text, [ev.evidence_id], 0.55,
                                     f"{PROMPT_VERSION}@llm"),
        ))
        existing_proc.append(text)
        added["procedures"] += 1

    facts.completeness.diagnoses = "found" if facts.diagnoses else "not_found"
    facts.completeness.medications = "found" if facts.medications else "not_found"
    facts.completeness.procedures = "found" if facts.procedures else "none_applicable"
    return {"status": "enriched", "added": added, "dropped_no_anchor": dropped_no_anchor,
            "dropped_bill_page": dropped_bill_page,
            "prompt_version": PROMPT_VERSION}
