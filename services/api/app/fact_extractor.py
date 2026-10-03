"""Conservative evidence-bound candidate extraction for the five REQ-03 fields."""

import re
from collections import Counter
from decimal import Decimal
from uuid import uuid4

from .cost_breakdown import CostAmount, LABEL_ROLES, NUMBER, cost_pairs

EXTRACTOR_VERSION = "evidence-pattern-candidate-v6"
FIELD_TYPES = ("diagnosis", "surgery", "medication", "stay_days", "total_cost")
# Pages that cannot be tied to a visit stay explicitly unattributed; they never
# merge into a primary encounter.
UNATTRIBUTED = "encounter:unattributed"
LABELS = {
    "diagnosis": r"(?:诊断|初步诊断|入院诊断|出院诊断)",
    "surgery": r"(?:手术|术式|手术名称)",
    "medication": r"(?:用药|药物|药品名称|出院带药|医嘱用药|带药)",
}
MEDICATION_PHASES = ("inpatient", "discharge", "outpatient", "charge_item", "plan", "unknown")
# Phase cues are judged only inside the candidate's own quote/label span.
PHASE_CUES = (
    ("discharge", r"出院带药|出院医嘱|出院用药|带药"),
    ("plan", r"下次|天后复诊|天后行|复诊行|行第\s*\d+\s*针|下次注射"),
    ("charge_item", r"收费明细|费用清单|费用明细|收费项目"),
    ("inpatient", r"住院|长期医嘱|临时医嘱|在院医嘱"),
    ("outpatient", r"门诊|处方"),
)
DATE_TOKEN = r"\d{2,4}[-年/.]\d{1,2}[-月/.]\d{1,2}日?"
DATE_TOKEN_RE = re.compile(r"(?<!\d)(" + DATE_TOKEN + r")(?!\d)")
DATE_PARTS_RE = re.compile(r"(\d{2,4})[-年/.](\d{1,2})[-月/.](\d{1,2})")
ADMISSION_RE = re.compile(r"(?:入院|入住)(?:时间|日期)\s*[:：]?\s*(" + DATE_TOKEN + r")")
DISCHARGE_RE = re.compile(r"出院(?:时间|日期)\s*[:：]?\s*(" + DATE_TOKEN + r")")
# Years are only counted in date or explicit-year contexts; bare 19xx/20xx runs are
# amounts, ids and counts far more often than years.
YEAR_CONTEXT_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})年(?!\d)")


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


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _source_bound(value: str, *sources: str) -> bool:
    """Whitespace-insensitive substring binding, same rule as report_builder._verbatim."""
    compacted = _compact(value)
    return bool(compacted) and any(compacted in _compact(source) for source in sources)


def _expand_year(year: str) -> int:
    value = int(year)
    if len(year) <= 2:
        # OCR-truncated two-digit years: 69-99 → 19xx, otherwise 20xx.
        return 1900 + value if value >= 69 else 2000 + value
    return value


def normalized_date(token: str) -> str | None:
    match = DATE_PARTS_RE.search(token or "")
    if not match:
        return None
    year, month, day = _expand_year(match.group(1)), int(match.group(2)), int(match.group(3))
    if not (1900 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _expand_value_dates(value: str) -> str:
    """Canonicalize dates embedded in entity values; two-digit years are window-expanded."""
    return DATE_TOKEN_RE.sub(lambda match: normalized_date(match.group(1)) or match.group(1), value)


def _text_years(text: str) -> list[int]:
    """Years in date tokens or explicit 'YYYY年' wording only — never bare numbers."""
    years = [_expand_year(DATE_PARTS_RE.search(match.group(1)).group(1))
             for match in DATE_TOKEN_RE.finditer(text or "")]
    years.extend(int(match.group(1)) for match in YEAR_CONTEXT_RE.finditer(text or ""))
    return years


def case_year_mode(texts) -> int | None:
    """Most frequent year across the case, but only on a strict majority.

    Years are read from date tokens and explicit 'YYYY年' wording, so amounts like
    '2000元' never vote. A tied top count (e.g. one 2020 page vs one 2025 page) is
    ambiguous: the years must then stay in conflict semantics instead of one side
    silently winning. OCR century errors push years backward, so a real majority
    resists a single polluted page far better than min/max.
    """
    counts: Counter = Counter()
    for text in texts:
        counts.update(_text_years(text))
    if not counts:
        return None
    ranked = counts.most_common(2)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def value_years(value: str) -> list[int]:
    years = []
    for year in _text_years(value):
        if year not in years:
            years.append(year)
    return years


def case_date_index(texts) -> dict:
    """(month, day) -> years seen across the case's dated text."""
    index: dict = {}
    for text in texts:
        for match in DATE_TOKEN_RE.finditer(text or ""):
            iso = normalized_date(match.group(1))
            if iso:
                index.setdefault(iso[5:], set()).add(int(iso[:4]))
    return index


def year_unresolvable(value, year_mode: int | None = None, date_index: dict | None = None) -> bool:
    """True when a value's embedded year cannot be reconciled with the case.

    A strict case-year majority decides; without one, a same month-day appearing
    elsewhere under a different year is a direct contradiction and stays unresolvable.
    """
    if not isinstance(value, str):
        return False
    if year_mode is not None:
        years = value_years(value)
        return bool(years) and any(abs(year - year_mode) > 1 for year in years)
    if not date_index:
        return False
    return any(token and any(abs(int(token[:4]) - other) > 1 for other in date_index.get(token[5:], ()))
               for token in (normalized_date(match.group(1)) for match in DATE_TOKEN_RE.finditer(value)))


def medication_phase(text: str) -> str:
    for phase, pattern in PHASE_CUES:
        if re.search(pattern, text or ""):
            return phase
    return "unknown"


def medication_value(drug: str, context: str) -> dict:
    return {"drug_name": clean_value(drug), "dose": None, "frequency": None,
            "route": None, "phase": medication_phase(context)}


def _normalize_medication(value: dict):
    drug = value.get("drug_name")
    if not isinstance(drug, str) or not clean_value(drug):
        return None
    fields = {key: (clean_value(value[key]) if isinstance(value.get(key), str) and clean_value(value[key]) else None)
              for key in ("dose", "frequency", "route")}
    phase = value.get("phase")
    return {"drug_name": clean_value(drug), **fields,
            "phase": phase if phase in MEDICATION_PHASES else "unknown"}


def normalize_value(fact_type: str, value):
    if fact_type == "diagnosis" and isinstance(value, str):
        return _expand_value_dates(re.sub(r"^(?:疑似|考虑|待排|可能)\s*", "", clean_value(value)))
    if fact_type == "surgery" and isinstance(value, str):
        return _expand_value_dates(clean_value(value))
    if fact_type == "medication":
        if isinstance(value, dict):
            return _normalize_medication(value)
        if isinstance(value, str):
            return _expand_value_dates(clean_value(value))
        return value
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


def candidate(fact_type: str, value, raw: str, evidence_id, *, unit=None, confidence=0.72,
              encounter_key=UNATTRIBUTED):
    return {
        "fact_id": uuid4(), "fact_type": fact_type, "value": value,
        "raw_value": raw, "status": "observed", "assertion": assertion_for(raw),
        "evidence_ids": [str(evidence_id)], "confidence_score": confidence,
        "confidence_method": EXTRACTOR_VERSION, "unit": unit, "derivation": None,
        "alternatives": [], "missing_reason": None, "extractor_version": EXTRACTOR_VERSION,
        "encounter_key": encounter_key,
    }


def missing_fact(fact_type: str, reason: str, encounter_key=UNATTRIBUTED):
    return {
        "fact_id": uuid4(), "fact_type": fact_type, "value": None,
        "raw_value": None, "status": "missing", "assertion": "unknown",
        "evidence_ids": [], "confidence_score": None, "confidence_method": None,
        "unit": None, "derivation": None, "alternatives": [],
        "missing_reason": reason, "extractor_version": EXTRACTOR_VERSION,
        "encounter_key": encounter_key,
    }


def _year_gated(fact_type: str, item: dict, year_mode: int | None, date_index: dict | None) -> dict:
    """A present-tense value whose embedded year contradicts the case stays conservative.

    The fact degrades to missing and keeps its raw_value/evidence chain for as long as
    it remains the slot's standing fact; once a resolvable candidate occupies the same
    slot, _merge_fact supersedes the unresolvable one (the surviving fact is the
    resolved value, so the dropped year's chain is intentionally not carried on it).
    """
    if (item["status"] != "observed" or item["assertion"] != "present" or
            not year_unresolvable(item["value"], year_mode, date_index)):
        return item
    return {**item, "value": None, "status": "missing", "missing_reason": "year_unresolvable"}


def medication_slot(value) -> str:
    """Medication facts keep one slot per (drug, phase); other types share their type slot."""
    if isinstance(value, dict) and isinstance(value.get("drug_name"), str) and clean_value(value["drug_name"]):
        return _compact(value["drug_name"]) + ":" + str(value.get("phase") or "unknown")
    return ""


def _same_value(fact_type: str, a, b) -> bool:
    if fact_type == "medication" and isinstance(a, dict) and isinstance(b, dict):
        return (_compact(a.get("drug_name")) == _compact(b.get("drug_name")) and
                a.get("phase") == b.get("phase") and
                all((a.get(key) or None) == (b.get(key) or None)
                    for key in ("dose", "frequency", "route")))
    return a == b


def _merge_fact(current, incoming):
    """Keep every sourced alternative; later candidates cannot resolve a conflict."""
    if incoming["status"] == "missing":
        # A conservatively-missing candidate never overwrites a sourced value.
        return current if current is not None else incoming
    if current is None or current['status'] == 'missing':
        return incoming
    if current['status'] != 'conflict' and _same_value(current['fact_type'], current['value'], incoming['value']):
        return {**current, 'assertion': current['assertion'] if current['assertion'] == incoming['assertion'] else 'unknown',
            'evidence_ids': list(dict.fromkeys(
            current['evidence_ids'] + incoming['evidence_ids']))}
    alternatives = [dict(item, evidence_ids=list(item['evidence_ids'])) for item in
                    (current['alternatives'] if current['status'] == 'conflict' else [
                        {'value': current['value'], 'evidence_ids': current['evidence_ids']}])]
    existing = next((item for item in alternatives if _same_value(current['fact_type'], item['value'], incoming['value'])), None)
    if existing is not None:
        existing['evidence_ids'] = list(dict.fromkeys(existing['evidence_ids'] + incoming['evidence_ids']))
    else:
        alternatives.append({'value': incoming['value'], 'evidence_ids': list(incoming['evidence_ids'])})
    return {**current, 'value': None, 'raw_value': None, 'status': 'conflict',
            'assertion': 'unknown', 'evidence_ids': [], 'confidence_score': None,
            'confidence_method': None, 'unit': None, 'alternatives': alternatives,
            'missing_reason': None}


def extract_facts(evidence_rows):
    texts = [row["text"] for row in evidence_rows if row.get("text")]
    year_mode = case_year_mode(texts)
    date_index = year_mode is None and case_date_index(texts) or None
    found = {}
    for row in evidence_rows:
        key = row.get("encounter_key") or UNATTRIBUTED
        text, evidence_id = row["text"], row["evidence_id"]
        for fact_type, label in LABELS.items():
            # Medication keeps one slot per (drug, phase) so a discharge prescription and
            # a future injection plan coexist. Diagnosis/surgery keep the first documented
            # value per encounter: admission/discharge wording progress is clinically
            # normal, and a same-type conflict has no human resolution channel downstream
            # (releases hard-block on any conflict fact), so later variants only merge
            # when they repeat the standing value.
            for match in re.finditer(label + r"\s*[:：]\s*([^\n]{1,100})", text):
                raw, value = clean_value(match.group(0)), clean_value(match.group(1))
                if not value:
                    continue
                if fact_type == "medication":
                    item = candidate(fact_type, normalize_value("medication",
                        medication_value(value, match.group(0))), raw, evidence_id, encounter_key=key)
                else:
                    item = candidate(fact_type, normalize_value(fact_type, value), raw, evidence_id,
                                     encounter_key=key)
                if item["value"] is None:
                    continue
                slot = (key, fact_type, medication_slot(item["value"]))
                current = found.get(slot)
                if (fact_type != "medication" and current is not None and
                        current["status"] not in ("missing",) and
                        not _same_value(fact_type, current["value"], item["value"])):
                    continue
                item = _year_gated(fact_type, item, year_mode, date_index)
                found[slot] = _merge_fact(current, item)
        for stay in re.finditer(r"住院\s*(?:共|时长|天数)?\s*[:：]?\s*(\d{1,4}(?:\.\d{1,4})?)\s*天", text):
            slot = (key, "stay_days", "")
            found[slot] = _merge_fact(found.get(slot), _year_gated("stay_days", candidate("stay_days",
                normalize_value("stay_days", stay.group(1)), clean_value(stay.group(0)),
                evidence_id, unit="day", confidence=0.9, encounter_key=key), year_mode, date_index))
        for cost in cost_pairs(text):
            # A category/detail subtotal or payment amount must not become the case total.
            if LABEL_ROLES[cost['label']]=='total':
                slot = (key, "total_cost", "")
                found[slot] = _merge_fact(found.get(slot), candidate('total_cost',
                    {'amount_minor':cost['amount_minor'],'currency':cost['currency']},cost['quote'],
                    evidence_id,unit='CNY',confidence=.9,encounter_key=key))
    for fact_type in FIELD_TYPES:
        if not any(slot[1] == fact_type for slot in found):
            found[(UNATTRIBUTED, fact_type, "")] = missing_fact(fact_type, "not_documented_in_parsed_materials")
    return [dict(fact) for _key, fact in
            sorted(found.items(), key=lambda item: (item[0][1], item[0][0], item[0][2]))]


def _date_record() -> dict:
    return {"status": "missing", "date": None, "alternatives": [], "evidence_ids": []}


def _merge_date(record: dict, iso: str, evidence_id: str, year_mode: int | None) -> None:
    if year_mode is not None and abs(int(iso[:4]) - year_mode) > 1:
        # Year cannot be reconciled with the case; keep it visible but never usable.
        unresolved = record.setdefault("unresolved", [])
        if int(iso[:4]) not in unresolved:
            unresolved.append(int(iso[:4]))
        return
    if record["status"] == "observed" and record["date"] == iso:
        record["evidence_ids"] = list(dict.fromkeys(record["evidence_ids"] + [evidence_id]))
        return
    if record["status"] == "missing":
        record.update(status="observed", date=iso, evidence_ids=[evidence_id])
        return
    alternatives = record["alternatives"] or ([record["date"]] if record["date"] else [])
    if iso not in alternatives:
        alternatives.append(iso)
    record.update(status="conflict", date=None, alternatives=alternatives,
                  evidence_ids=list(dict.fromkeys(record["evidence_ids"] + [evidence_id])))


def collect_encounter_dates(evidence_rows) -> dict:
    """Per-encounter normalized admission/discharge dates with their evidence chain.

    Dates whose year contradicts the case-wide year mode are recorded as unresolved
    instead of being stored; remaining disagreements stay as explicit conflicts.
    """
    year_mode = case_year_mode([row["text"] for row in evidence_rows if row.get("text")])
    found: dict = {}
    for row in evidence_rows:
        key = row.get("encounter_key") or UNATTRIBUTED
        text = row.get("text") or ""
        for side, pattern in (("admission", ADMISSION_RE), ("discharge", DISCHARGE_RE)):
            for match in pattern.finditer(text):
                iso = normalized_date(match.group(1))
                if iso is None:
                    continue
                record = found.setdefault(key, {"admission": _date_record(), "discharge": _date_record()})
                _merge_date(record[side], iso, str(row["evidence_id"]), year_mode)
    return {key: value for key, value in found.items()
            if value["admission"]["status"] != "missing" or value["discharge"]["status"] != "missing"}


def merge_model_candidates(rule_facts, model_candidates, evidence_rows, year_mode=None):
    texts = [row["text"] for row in evidence_rows if row.get("text")]
    if year_mode is None:
        year_mode = case_year_mode(texts)
    date_index = year_mode is None and case_date_index(texts) or None
    facts = {}
    for item in rule_facts:
        key = item.get("encounter_key") or UNATTRIBUTED
        value = item.get("value")
        if value is None and item.get("alternatives"):
            value = item["alternatives"][0].get("value")
        facts[(key, item["fact_type"], medication_slot(value))] = item
    for candidate_item in model_candidates:
        quote = candidate_item["evidence_quote"]
        if not quote.strip():
            continue
        source = next((row for row in evidence_rows if quote in row["text"]), None)
        if source is None:
            continue
        fact_type = candidate_item["fact_type"]
        if fact_type == "medication":
            phase = medication_phase(quote)
            if phase != "unknown":
                # Prefer the page whose own text corroborates the quote's phase.
                pattern = dict(PHASE_CUES)[phase]
                source = next((row for row in evidence_rows if quote in row["text"]
                               and re.search(pattern, row["text"])), source)
        raw_value = candidate_item["raw_value"]
        # A candidate whose raw value is absent from its quote and source page has no
        # binding to the material and is dropped before it can become observed.
        if not _source_bound(raw_value, quote, source["text"]):
            continue
        if fact_type == "medication":
            drug_name = candidate_item.get("drug_name") or raw_value
            if not _source_bound(drug_name, quote, source["text"]):
                continue
            # Structured details are kept only when the quote itself carries them.
            details = {key: (candidate_item.get(key) if _source_bound(candidate_item.get(key) or "", quote, source["text"]) else None)
                       for key in ("dose", "frequency", "route")}
            model_value = normalize_value("medication", {
                "drug_name": drug_name, **details, "phase": medication_phase(quote)})
        else:
            model_value = normalize_value(fact_type, candidate_item["normalized_value"])
        if model_value is None or (isinstance(model_value, str) and not model_value.strip()):
            continue
        if fact_type not in ("total_cost", "medication"):
            if candidate_item["assertion"] == "present":
                if normalize_value(fact_type, raw_value) != model_value:
                    # Present-tense values must be derivable from the bound raw text.
                    continue
            elif isinstance(model_value, str):
                # The model also self-reports the assertion, so a qualifier is no licence:
                # the stripped entity must still be verbatim in the quote or its page.
                if not _source_bound(model_value, quote, source["text"]):
                    continue
            elif not _source_bound(str(model_value), quote, source["text"]):
                continue
        if fact_type=='total_cost':
            supported=[c for c in cost_pairs(quote) if LABEL_ROLES[c['label']]=='total' and
                {'amount_minor':c['amount_minor'],'currency':c['currency']}==model_value]
            if not supported or not any(c['label']==supported[0]['label'] and
                {'amount_minor':c['amount_minor'],'currency':c['currency']}==model_value for c in cost_pairs(source['text'])):
                continue
            raw_value=supported[0]['quote']
        key = source.get("encounter_key") or UNATTRIBUTED
        incoming = candidate(fact_type, model_value, raw_value, source["evidence_id"],
            unit="day" if fact_type == "stay_days" else ("CNY" if fact_type == "total_cost" else None),
            confidence=candidate_item.get("confidence_score"), encounter_key=key)
        incoming['assertion'] = candidate_item['assertion']
        if fact_type in LABELS:
            source_assertion = _quoted_context_assertion(quote, source['text'])
            if (source_assertion == 'present' and
                    incoming['assertion'] in ('negated', 'suspected', 'historical')):
                # The model self-reports assertions too: a qualifier its own cited
                # sentence does not carry is fabrication, and the verbatim present-
                # tense sentence is authoritative.
                incoming['assertion'] = 'present'
            elif source_assertion != 'present' and source_assertion != incoming['assertion']:
                incoming['assertion'] = 'unknown'
        incoming['confidence_method'] = 'llm-reported-uncalibrated-v1' if candidate_item.get('confidence_score') is not None else None
        incoming = _year_gated(fact_type, incoming, year_mode, date_index)
        slot = (key, fact_type, medication_slot(model_value))
        facts[slot] = _merge_fact(facts.get(slot), incoming)
    occupied_types = {slot[1] for slot, fact in facts.items() if fact["status"] != "missing"}
    for slot in [slot for slot, fact in facts.items()
                 if fact["status"] == "missing" and slot[1] in occupied_types]:
        del facts[slot]
    return [dict(fact) for _key, fact in
            sorted(facts.items(), key=lambda item: (item[0][1], item[0][0], item[0][2]))]
