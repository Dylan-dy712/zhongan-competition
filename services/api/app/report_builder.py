"""REQ-07 report validation and conservative section completion."""

import re
from uuid import uuid4

from .contracts.core import Claim, ReportSection
from .fact_extractor import DATE_TOKEN_RE, normalized_date

SECTION_TYPES = ("diagnosis_explanation", "treatment_review", "cost_explanation",
                 "recovery_plan", "emotional_support", "next_visit_advice")
POLICY_VERSION = "report-safety-v3"
UNSAFE_PATTERNS = (r"自行(?:停药|换药|加药)", r"保证(?:治愈|康复|有效)", r"医生(?:开错|误诊)")
NEUTRAL_TEAM = "您的诊疗团队"
CLINICAL_TITLES = ("主治", "主管", "主刀", "术者", "手术者", "接诊")
# The longest alternatives come first so '手术者' is never read as '术者'+'…'.
_TITLE_ONLY = re.compile(r"主治医师|主治医生|主管医师|主管医生|主刀医生|主刀|手术者|术者|接诊医师|接诊医生")
_NAME_RUN = re.compile(r"(?:是|为)?([\u4e00-\u9fa5]{2,6})")
_RUN_THEN_DOCTOR = re.compile(r"(?P<run>[\u4e00-\u9fa5]{2,4})(?:医生|医师)")
# A non-clinical role must bind the name adjacently (label right before or after the
# name, allowing a short filler), so a department word like '内科' inside '内科会诊意见'
# is never read as a person.
_NON_CLINICAL_LABEL = r"(?:(?:检验)?(?:审核者|审核医师|报告者|报告医师|记录者)|手术助手|工助|Ⅰ助|Ⅱ助|进修)"
# Two-character verbs/nouns that frequently precede or replace real names in clinical
# boilerplate; treating them as names corrupts sentences.
NAME_STOPWORDS = ("交代", "交待", "查房", "沟通", "建议", "复查", "随访", "会诊", "记录",
                  "查体", "查看", "评估", "巡视", "值班", "门诊", "病房", "医师", "医生")
_SENTENCE_SPLIT = re.compile(r"[\n。；;，]")


def _plausible_name(candidate: str) -> bool:
    return bool(candidate) and not candidate.endswith(("科", "室", "院", "区", "房")) and \
        not any(word in candidate for word in NAME_STOPWORDS)


def _resolve_name(candidates, corpus: str) -> str | None:
    for candidate in candidates:
        if candidate and candidate in corpus and _plausible_name(candidate):
            return candidate
    return None


def _non_clinical_adjacent(sentence: str, name: str) -> bool:
    for match in re.finditer(re.escape(name), sentence):
        prefix, suffix = sentence[:match.start()], sentence[match.end():]
        if re.search(_NON_CLINICAL_LABEL + r"\s*[:：]?\s*[\u4e00-\u9fa5]{0,2}$", prefix):
            return True
        if re.match(r"[\u4e00-\u9fa5]{0,2}\s*[:：]?\s*" + _NON_CLINICAL_LABEL, suffix):
            return True
    return False


def _neutralize_role_claims(text: str, sources: list[str]) -> str:
    """Rewrite doctor-role mentions the cited material cannot support.

    A clinical title bound to a name must co-occur with it in one cited sentence, and a
    person the material only records as reviewer/reporter/assistant (adjacent to that
    role label) must not be offered as the treating doctor; both are replaced with a
    neutral team reference so the wrong-role sentence never enters the report. Only the
    resolved name span is rewritten, keeping surrounding words intact.
    """
    corpus = "\n".join(sources)
    if not corpus.strip():
        return text
    sentences = [part for source in sources for part in _SENTENCE_SPLIT.split(source or "") if part]

    # Pass 1: a clinical title followed by a name the corpus knows.
    parts, cursor = [], 0
    for match in _TITLE_ONLY.finditer(text):
        rest = _NAME_RUN.match(text, match.end())
        if rest is None:
            continue
        run = rest.group(1)
        name = _resolve_name([run[:4], run[:3], run[:2]], corpus)
        if name is None:
            continue
        title = re.sub(r"(?:医师|医生)$", "", match.group(0))
        if any(name in part and title in part for part in sentences):
            continue
        parts.append(text[cursor:match.start()])
        parts.append(NEUTRAL_TEAM)
        cursor = rest.start(1) + len(name)
        # A name written as '…李四医生' carries its doctor suffix; consume it too.
        if text[cursor:cursor + 2] in ("医生", "医师"):
            cursor += 2
    text = "".join(parts) + text[cursor:]

    # Pass 2: a name the corpus only binds to a non-clinical role, called a doctor.
    def name_match(match):
        run = match.group("run")
        name = _resolve_name([run[-4:], run[-3:], run[-2:]], corpus)
        if name is None:
            return match.group(0)
        bound = [part for part in sentences if name in part]
        clinical = any(any(title in part for title in CLINICAL_TITLES) for part in bound)
        adjacent = any(_non_clinical_adjacent(part, name) for part in bound)
        if not (adjacent and not clinical):
            return match.group(0)
        return run[:len(run) - len(name)] + NEUTRAL_TEAM

    return _RUN_THEN_DOCTOR.sub(name_match, text)


def map_report_sources(draft: dict, evidence: dict[str, str], sources: dict[str, str] | None = None) -> dict:
    """Bind exact quotes without modifying the model output retained for audit."""
    sources = sources or {}
    def refs(quote, corpus):
        match = next((key for key, text in corpus.items() if quote and quote.strip() and quote in text), None)
        return [match] if match else []

    return {
        "sections": [{"section_type": section.get("section_type"), "claims": [
            {**claim, "evidence_refs": refs(claim.get("evidence_quote"), evidence),
             "source_refs": list(dict.fromkeys(claim.get("source_refs", []) +
                 (refs(claim.get("source_quote"), sources) if claim.get("claim_type") == "patient_statement" else [])))}
            for claim in section.get("claims", [])
        ]} for section in draft.get("sections", [])],
        "actions": [{**action, "source_refs": list(dict.fromkeys(
            action.get("source_refs", []) + refs(action.get("source_quote"), evidence) +
            refs(action.get("source_quote"), sources)))}
            for action in draft.get("actions", [])],
    }


def _verbatim(text: str, sources: list[str]) -> bool:
    text = re.sub(r"\s+", "", text)
    return bool(text) and any(text in re.sub(r"\s+", "", source) for source in sources)


def _fact_preserved(text: str, sources: list[str]) -> bool:
    text = re.sub(r"\s+", "", text).rstrip("。")
    for source in sources:
        source = re.sub(r"\s+", "", source).rstrip("。")
        source = re.sub(r"^(?:门诊|入院|出院|病理)?诊断[:：]", "", source)
        if text == source:
            return True
    return False


def _unsafe(text: str) -> bool:
    text = re.sub(r"(?:不要|不得|切勿|请勿|避免|禁止|不建议|不应|不能)自行(?:停药|换药|加药)", "", text)
    return any(re.search(pattern, text) for pattern in UNSAFE_PATTERNS)


def _claim_date_conflicts(text: str, structured_dates: dict | None) -> bool:
    """True when a claim date shares month-day with a structured date but flips its year."""
    claim_dates = [normalized_date(match.group(1)) for match in DATE_TOKEN_RE.finditer(text)]
    claim_dates = [value for value in claim_dates if value]
    if not claim_dates:
        return False
    for record in (structured_dates or {}).values():
        for side in record.values():
            known = list(side.get("alternatives") or [])
            if side.get("date"):
                known.append(side["date"])
            for claim_date in claim_dates:
                for reference in known:
                    if claim_date[5:] == reference[5:] and abs(int(claim_date[:4]) - int(reference[:4])) > 1:
                        return True
    return False


def validate_and_complete(draft: dict, valid_evidence: dict[str, str], approved_knowledge: set[str],
                          valid_source_refs: dict[str, str], structured_dates: dict | None = None
                          ) -> tuple[list[ReportSection], list[dict], list[str]]:
    errors, sections = [], []
    by_section = {item.get("section_type"): item.get("claims", []) for item in draft.get("sections", [])}
    for section_type in SECTION_TYPES:
        claims = []
        for raw in by_section.get(section_type, []):
            evidence = [x for x in raw.get("evidence_refs", []) if x in valid_evidence]
            knowledge = [x for x in raw.get("knowledge_refs", []) if x in approved_knowledge]
            sources = [x for x in raw.get("source_refs", []) if x in valid_source_refs]
            claim_type = raw.get("claim_type")
            if claim_type == "case_fact" and not evidence:
                errors.append("CASE_FACT_WITHOUT_VALID_EVIDENCE"); continue
            if claim_type == "professional_explanation" and not knowledge:
                errors.append("UNAPPROVED_KNOWLEDGE_REFERENCE"); continue
            if claim_type == "patient_statement" and not sources:
                errors.append("PATIENT_STATEMENT_WITHOUT_SOURCE"); continue
            text = str(raw.get("text", "")).strip()
            if not text or _unsafe(text):
                errors.append("UNSAFE_OR_EMPTY_CLAIM"); continue
            review_required = claim_type in {"professional_explanation", "to_confirm", "service_suggestion"}
            if claim_type not in {"professional_explanation", "patient_statement"}:
                # Case facts are checked against their cited spans; other claim types may
                # fall back to the whole evidence corpus. patient_statement stays exempt:
                # user_sources are the user's frozen words and are never rewritten here.
                # Unverifiable mentions stay put: the existing provenance rules already
                # keep them out of ready reports.
                scope = [valid_evidence[x] for x in evidence] if evidence else (
                    [] if claim_type == "case_fact" else list(valid_evidence.values()))
                corrected = _neutralize_role_claims(text, scope)
                if corrected != text:
                    text = corrected
                    review_required = True
            if claim_type == "service_suggestion":
                # Model-assigned labels do not prove that advice is non-clinical or supported.
                errors.append("SERVICE_SUGGESTION_REQUIRES_REVIEW")
            if claim_type == "patient_statement" and not _fact_preserved(text, [valid_source_refs[x] for x in sources]):
                review_required = True
                errors.append("PATIENT_STATEMENT_REQUIRES_REVIEW")
            if claim_type == "case_fact" and not _fact_preserved(text, [valid_evidence[x] for x in evidence]):
                # A valid ID proves provenance, not that a paraphrase preserves the fact.
                review_required = True
                errors.append("CASE_FACT_REQUIRES_REVIEW")
            if claim_type == "case_fact" and _claim_date_conflicts(text, structured_dates):
                # A date claim contradicting the normalized timeline cannot yield a ready report.
                review_required = True
                errors.append("CLAIM_DATE_CONFLICTS_WITH_STRUCTURED_DATES")
            try:
                claims.append(Claim(claim_id=uuid4(), text=text, claim_type=claim_type,
                    evidence_refs=evidence, knowledge_refs=knowledge, source_refs=sources,
                    review_status="pending" if review_required else "not_required"))
            except Exception:
                errors.append("INVALID_CLAIM")
        if not claims:
            claims = [Claim(claim_id=uuid4(), text="当前材料不足，相关内容需要结合原始医嘱或由专业人员进一步确认。",
                            claim_type="to_confirm", review_status="pending")]
        sections.append(ReportSection(section_type=section_type, claims=claims))
    actions = []
    for raw in draft.get("actions", [])[:3]:
        text = str(raw.get("action_text", "")).strip()
        if not text or _unsafe(text):
            errors.append("UNSAFE_OR_EMPTY_ACTION"); continue
        refs = [x for x in raw.get("source_refs", []) if x in valid_evidence or x in valid_source_refs]
        if not refs:
            errors.append("ACTION_WITHOUT_SOURCE"); continue
        due_at, due_source = raw.get("due_at"), raw.get("due_source", "unknown")
        source_texts = [valid_evidence[x] if x in valid_evidence else valid_source_refs[x] for x in refs]
        if not (_fact_preserved(text, source_texts) or
                (due_at and _fact_preserved(f"{text} {due_at}", source_texts))):
            errors.append("ACTION_REQUIRES_REVIEW")
        due_texts = ([valid_evidence[x] for x in refs if x in valid_evidence] if due_source == "medical_order"
                     else [valid_source_refs[x] for x in refs if x in valid_source_refs] if due_source == "user_request"
                     else [])
        if due_at and due_source == "unknown":
            errors.append("ACTION_DUE_WITHOUT_SOURCE"); due_at = None
        elif due_source != "unknown" and not due_texts:
            errors.append("ACTION_DUE_SOURCE_MISMATCH"); due_at, due_source = None, "unknown"
        elif due_at and not _verbatim(due_at, due_texts):
            errors.append("ACTION_DUE_REQUIRES_REVIEW"); due_at, due_source = None, "unknown"
        actions.append({**raw, "source_refs": refs, "due_at": due_at,
                        "due_source": due_source, "priority": len(actions) + 1})
    return sections, actions, list(dict.fromkeys(errors))
