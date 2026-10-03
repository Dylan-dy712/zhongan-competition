"""REQ-05 conservative rule candidates and semantic-candidate reconciliation."""

import re
from .cost_breakdown import build_cost_breakdown
from uuid import uuid4

from .contracts.knowledge import DiseaseCode

RULE_VERSION = "insight-rules-v2"
LABEL_CATEGORY = {
    "CLIN_MEDICATION_CONTEXT_REVIEW": "clinical",
    "CLIN_EXAM_JUSTIFICATION_REVIEW": "clinical",
    "COST_SELF_PAY_DEVIATION": "cost",
    "COST_AMOUNT_RECONCILIATION": "cost",
    "EXP_TERMINOLOGY_BARRIER": "experience",
    "EXP_DISCHARGE_GUIDANCE_GAP": "experience",
}
DISEASE_TERMS = {
    DiseaseCode.fx: ("骨折",), DiseaseCode.fy: ("肺炎", "CAP"),
    DiseaseCode.gx: ("冠心病", "心肌梗死", "心绞痛", "PCI"),
    DiseaseCode.yz: ("腰椎间盘突出",), DiseaseCode.tn: ("2型糖尿病", "Ⅱ型糖尿病"),
}


def infer_disease_code(text: str) -> DiseaseCode | None:
    for code, terms in DISEASE_TERMS.items():
        if any(term.lower() in text.lower() for term in terms):
            return code
    return None


def _insight(label, evidence_ids, rationale, action, *, knowledge_refs=(),
             severity="undetermined", judgment="candidate", confidence=None,
             confidence_method=None):
    category = LABEL_CATEGORY[label]
    clinical = category == "clinical"
    return {
        "insight_id": uuid4(), "category": category, "label": label,
        "severity": severity, "confidence": confidence,
        "confidence_method": confidence_method,
        "evidence_ids": list(dict.fromkeys(str(x) for x in evidence_ids)),
        "rationale": rationale, "uncertainty": None,
        "suggested_action": action, "review_required": clinical or judgment != "supported",
        "review_status": "pending" if clinical or judgment != "supported" else "not_required",
        "judgment_status": judgment, "rule_version": RULE_VERSION,
        "knowledge_refs": list(dict.fromkeys(knowledge_refs)),
    }


def deterministic_candidates(evidence_rows, knowledge_entries=()):
    results = []
    # Compare only explicit labels in the same physical source scope; a page is not proof of a bill.
    scopes={}
    for field in build_cost_breakdown(evidence_rows).fields:
        if field.role in {'total','detail_subtotal'}:
            scopes.setdefault(field.scope_ref,{'total':[],'detail_subtotal':[]})[field.role].append(field)
    for scope in scopes.values():
        if not scope['total'] or not scope['detail_subtotal']:
            continue
        if any(field.amount.status!='observed' for fields in scope.values() for field in fields):
            continue
        totals={field.amount.value.amount_minor for field in scope['total']}
        details={field.amount.value.amount_minor for field in scope['detail_subtotal']}
        if len(totals)==len(details)==1 and totals!=details:
            results.append(_insight('COST_AMOUNT_RECONCILIATION',
                [ref for fields in scope.values() for field in fields for ref in field.amount.evidence_ids],
                '同页或同一原文块明确记载的总费用与明细合计金额不同，尚未确认两者是否属于同张单据及相同结算范围。',
                '核对单据身份、明细范围、重复页及折扣/支付口径；不能据此认定收费错误。',
                severity='medium',judgment='indeterminate'))
    # Important terminology appearing in supplied material creates an explanation need, not a claim about ability.
    seen_terms = set()
    for entry in knowledge_entries:
        if entry.slot not in {"S2", "S11"} or not entry.title or len(entry.title) < 2:
            continue
        for row in evidence_rows:
            if entry.title in row["text"] and entry.title not in seen_terms:
                seen_terms.add(entry.title)
                results.append(_insight(
                    "EXP_TERMINOLOGY_BARRIER", [row["evidence_id"]],
                    f"当前材料出现重要术语“{entry.title}”，可提供与病例事实分开的通俗解释。",
                    "在报告中解释该术语，并引用当前材料位置。",
                    knowledge_refs=[entry.entry_id], severity="low", judgment="supported"))
                break
    return results


def merge_semantic_candidates(rule_candidates, semantic_candidates, evidence_rows, knowledge_ids):
    results = list(rule_candidates)
    known = {(x["label"], tuple(x["evidence_ids"])) for x in results}
    for item in semantic_candidates:
        label = item.get("label")
        if label not in LABEL_CATEGORY or label == "COST_SELF_PAY_DEVIATION":
            continue
        quote = item.get("evidence_quote", "")
        source = next((row for row in evidence_rows if quote and quote in row["text"]), None)
        if source is None:
            continue
        refs = [ref for ref in item.get("knowledge_refs", []) if ref in knowledge_ids]
        key = (label, (str(source["evidence_id"]),))
        if key in known:
            continue
        known.add(key)
        results.append(_insight(
            label, [source["evidence_id"]], item["rationale"], item["suggested_action"],
            knowledge_refs=refs, judgment="candidate", severity="undetermined",
            confidence=item.get("confidence"),
            confidence_method="llm-reported-uncalibrated-v1" if item.get("confidence") is not None else None))
    return results
