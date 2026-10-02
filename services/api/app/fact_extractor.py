"""Conservative evidence-bound candidate extraction for the five REQ-03 fields."""

import re
from decimal import Decimal, InvalidOperation
from uuid import uuid4

EXTRACTOR_VERSION = "evidence-pattern-candidate-v3"
FIELD_TYPES = ("diagnosis", "surgery", "medication", "stay_days", "total_cost")
LABELS = {
    "diagnosis": r"(?:诊断|初步诊断|入院诊断|出院诊断)",
    "surgery": r"(?:手术|术式|手术名称)",
    "medication": r"(?:用药|药物|药品名称)",
}


def assertion_for(raw: str) -> str:
    if re.search(r"(?:疑似|考虑|待排|可能)", raw):
        return "suspected"
    if re.search(r"(?:否认|未见|排除)", raw):
        return "negated"
    if re.search(r"(?:既往|曾有|曾行)", raw):
        return "historical"
    return "present"


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
        if isinstance(value, dict) and "amount_minor" in value:
            return {"amount_minor": int(value["amount_minor"]), "currency": value.get("currency", "CNY")}
        match = re.search(r"[0-9][0-9,]*(?:\.\d{1,2})?", str(value))
        if match:
            amount_minor = int((Decimal(match.group().replace(",", "")) * 100).quantize(Decimal("1")))
            return {"amount_minor": amount_minor, "currency": "CNY"}
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
        return {**current, 'evidence_ids': list(dict.fromkeys(
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
        for cost in re.finditer(r"(?:医疗总费用|总费用|费用合计|合计)\s*[:：]?\s*(?:人民币|CNY|￥|¥)?\s*([0-9][0-9,]*(?:\.\d{1,2})?)\s*元?", text, re.I):
            try:
                amount_minor = int((Decimal(cost.group(1).replace(",", "")) * 100).quantize(Decimal("1")))
            except InvalidOperation:
                continue
            found["total_cost"] = _merge_fact(found.get("total_cost"), candidate("total_cost",
                {"amount_minor": amount_minor, "currency": "CNY"}, clean_value(cost.group(0)),
                evidence_id, unit="CNY", confidence=0.9))
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
        incoming = candidate(fact_type, model_value, candidate_item["raw_value"], source["evidence_id"],
            unit="day" if fact_type == "stay_days" else ("CNY" if fact_type == "total_cost" else None),
            confidence=candidate_item.get("confidence_score"))
        incoming['assertion'] = candidate_item['assertion']
        incoming['confidence_method'] = 'llm-reported-uncalibrated-v1' if candidate_item.get('confidence_score') is not None else None
        facts[fact_type] = _merge_fact(facts[fact_type], incoming)
    return [facts[fact_type] for fact_type in FIELD_TYPES]
