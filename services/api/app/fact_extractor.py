"""Conservative evidence-bound candidate extraction for the five REQ-03 fields."""

import re
from decimal import Decimal
from uuid import uuid4

from .cost_breakdown import CostAmount, LABEL_ROLES, NUMBER, cost_pairs

EXTRACTOR_VERSION = "evidence-pattern-candidate-v5"
FIELD_TYPES = ("diagnosis", "surgery", "medication", "stay_days", "total_cost")
LABELS = {
    "diagnosis": r"(?:诊断|初步诊断|入院诊断|出院诊断)",
    "surgery": r"(?:手术|术式|手术名称)",
    "medication": r"(?:用药|药物|药品名称)",
}


def assertion_for(raw: str) -> str:
    # Remove double-negation phrases before checking standalone exclusion.
    uncertain = r"(?:尚未排除|未能排除|不能排除|无法排除|不除外|未排除)"
    remainder = re.sub(uncertain, "", raw)
    states = set()
    if re.search(uncertain, raw) or re.search(r"(?:疑似|考虑|待排|可能|待明确|待确诊)", remainder):
        states.add("suspected")
    if re.search(r"(?:否认|未见|排除|无证据支持)", remainder):
        states.add("negated")
    if re.search(r"(?:既往|曾有|曾行)", re.sub(r"否认\s*既往", "否认", remainder)):
        states.add("historical")
    return next(iter(states)) if len(states) == 1 else ("unknown" if states else "present")


def _quoted_context_assertion(quote: str, text: str) -> str:
    # ponytail: sentence-level cues are conservative; entity-specific scope needs medical NLP validation.
    states = set()
    for match in re.finditer(re.escape(quote), text):
        left = max((text.rfind(mark, 0, match.start()) for mark in '\n。；;'), default=-1) + 1
        right = re.search(r"[\n。；;]", text[match.end():])
        end = match.end() + right.start() if right else len(text)
        states.add(assertion_for(text[left:end]))
    return next(iter(states)) if len(states) == 1 else "unknown"


def clean_value(raw: str) -> str:
    return raw.strip().strip("。；;,， ")


def normalize_value(fact_type: str, value):
    if fact_type == "diagnosis" and isinstance(value, str):
        return re.sub(r"^(?:疑似|考虑|待排|可能)\s*", "", clean_value(value))
    if fact_type in {"surgery", "medication"} and isinstance(value, str):
        return clean_value(value)
    if fact_type == "stay_days":
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:天|days?)?\s*", str(value))
        if not match:
            return None
        days = Decimal(match.group(1))
        return int(days) if days == days.to_integral_value() else float(days)
    if fact_type == "total_cost":
        if isinstance(value, dict):
            try:
                return CostAmount.model_validate(value).model_dump()
            except ValueError:
                return None
        match=re.fullmatch(r"\s*(?:人民币|CNY|￥|¥)?\s*("+NUMBER+r")\s*(?:元|CNY)?\s*",str(value),re.I)
        if match:
            return {'amount_minor':int(Decimal(match.group(1).replace(',',''))*100),'currency':'CNY'}
        return None
    return value


def candidate(fact_type: str, value, raw: str, evidence_id, *, unit=None, confidence=0.72):
    return {
        "fact_id": uuid4(), "fact_type": fact_type, "value": value,
        "raw_value": raw, "status": "observed", "assertion": assertion_for(raw),
        "evidence_ids": [str(evidence_id)], "confidence_score": confidence,
        "confidence_method": EXTRACTOR_VERSION, "unit": unit, "derivation": None,
        "alternatives": [], "missing_reason": None, "extractor_version": EXTRACTOR_VERSION,
    }


def _merge_fact(current, incoming):
    """Keep every sourced alternative; later candidates cannot resolve a conflict."""
    if current is None or current['status'] == 'missing':
        return incoming
    if current['status'] != 'conflict' and current['value'] == incoming['value']:
        return {**current, 'assertion': current['assertion'] if current['assertion'] == incoming['assertion'] else 'unknown',
            'evidence_ids': list(dict.fromkeys(
            current['evidence_ids'] + incoming['evidence_ids']))}
    alternatives = [dict(item, evidence_ids=list(item['evidence_ids'])) for item in
                    (current['alternatives'] if current['status'] == 'conflict' else [
                        {'value': current['value'], 'evidence_ids': current['evidence_ids']}])]
    existing = next((item for item in alternatives if item['value'] == incoming['value']), None)
    if existing is not None:
        existing['evidence_ids'] = list(dict.fromkeys(existing['evidence_ids'] + incoming['evidence_ids']))
    else:
        alternatives.append({'value': incoming['value'], 'evidence_ids': list(incoming['evidence_ids'])})
    return {**current, 'value': None, 'raw_value': None, 'status': 'conflict',
            'assertion': 'unknown', 'evidence_ids': [], 'confidence_score': None,
            'confidence_method': None, 'unit': None, 'alternatives': alternatives,
            'missing_reason': None}


def extract_facts(evidence_rows):
    found = {}
    for row in evidence_rows:
        text, evidence_id = row["text"], row["evidence_id"]
        for fact_type, label in LABELS.items():
            match = re.search(label + r"\s*[:：]\s*([^\n]{1,100})", text)
            if match and fact_type not in found:
                raw, value = clean_value(match.group(0)), clean_value(match.group(1))
                if value:
                    found[fact_type] = candidate(fact_type, normalize_value(fact_type, value), raw, evidence_id)
        for stay in re.finditer(r"住院\s*(?:共|时长|天数)?\s*[:：]?\s*(\d{1,4}(?:\.\d{1,4})?)\s*天", text):
            found["stay_days"] = _merge_fact(found.get("stay_days"), candidate("stay_days",
                normalize_value("stay_days", stay.group(1)), clean_value(stay.group(0)),
                evidence_id, unit="day", confidence=0.9))
        for cost in cost_pairs(text):
            # A category/detail subtotal or payment amount must not become the case total.
            if LABEL_ROLES[cost['label']]=='total':
                found['total_cost'] = _merge_fact(found.get('total_cost'), candidate('total_cost',
                    {'amount_minor':cost['amount_minor'],'currency':cost['currency']},cost['quote'],
                    evidence_id,unit='CNY',confidence=.9))
    for fact_type in FIELD_TYPES:
        if fact_type not in found:
            found[fact_type] = {
                "fact_id": uuid4(), "fact_type": fact_type, "value": None,
                "raw_value": None, "status": "missing", "assertion": "unknown",
                "evidence_ids": [], "confidence_score": None, "confidence_method": None,
                "unit": None, "derivation": None, "alternatives": [],
                "missing_reason": "not_documented_in_parsed_materials", "extractor_version": EXTRACTOR_VERSION,
            }
    return [found[fact_type] for fact_type in FIELD_TYPES]


def merge_model_candidates(rule_facts, model_candidates, evidence_rows):
    facts = {item["fact_type"]: item for item in rule_facts}
    for candidate_item in model_candidates:
        quote = candidate_item["evidence_quote"]
        if not quote.strip():
            continue
        source = next((row for row in evidence_rows if quote in row["text"]), None)
        if source is None:
            continue
        fact_type = candidate_item["fact_type"]
        model_value = normalize_value(fact_type, candidate_item["normalized_value"])
        if model_value is None or (isinstance(model_value, str) and not model_value.strip()):
            continue
        raw_value=candidate_item['raw_value']
        if fact_type=='total_cost':
            supported=[c for c in cost_pairs(quote) if LABEL_ROLES[c['label']]=='total' and
                {'amount_minor':c['amount_minor'],'currency':c['currency']}==model_value]
            if not supported or not any(c['label']==supported[0]['label'] and
                {'amount_minor':c['amount_minor'],'currency':c['currency']}==model_value for c in cost_pairs(source['text'])):
                continue
            raw_value=supported[0]['quote']
        incoming = candidate(fact_type, model_value, raw_value, source["evidence_id"],
            unit="day" if fact_type == "stay_days" else ("CNY" if fact_type == "total_cost" else None),
            confidence=candidate_item.get("confidence_score"))
        incoming['assertion'] = candidate_item['assertion']
        if fact_type in LABELS:
            source_assertion = _quoted_context_assertion(quote, source['text'])
            if source_assertion != 'present' and source_assertion != incoming['assertion']:
                incoming['assertion'] = 'unknown'
        incoming['confidence_method'] = 'llm-reported-uncalibrated-v1' if candidate_item.get('confidence_score') is not None else None
        facts[fact_type] = _merge_fact(facts[fact_type], incoming)
    return [facts[fact_type] for fact_type in FIELD_TYPES]
