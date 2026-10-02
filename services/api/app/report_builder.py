"""REQ-07 report validation and conservative section completion."""

import re
from uuid import uuid4

from .contracts.core import Claim, ReportSection

SECTION_TYPES = ("diagnosis_explanation", "treatment_review", "cost_explanation",
                 "recovery_plan", "emotional_support", "next_visit_advice")
POLICY_VERSION = "report-safety-v2"
UNSAFE_PATTERNS = (r"自行(?:停药|换药|加药)", r"保证(?:治愈|康复|有效)", r"医生(?:开错|误诊)")


def map_report_sources(draft: dict, evidence: dict[str, str]) -> dict:
    """Bind exact quotes without modifying the model output retained for audit."""
    def refs(quote):
        match = next((key for key, text in evidence.items() if quote and quote.strip() and quote in text), None)
        return [match] if match else []

    return {
        "sections": [{"section_type": section.get("section_type"), "claims": [
            {**claim, "evidence_refs": refs(claim.get("evidence_quote"))}
            for claim in section.get("claims", [])
        ]} for section in draft.get("sections", [])],
        "actions": [{**action, "source_refs": list(dict.fromkeys(
            action.get("source_refs", []) + refs(action.get("source_quote"))))}
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


def validate_and_complete(draft: dict, valid_evidence: dict[str, str], approved_knowledge: set[str],
                          valid_source_refs: dict[str, str]) -> tuple[list[ReportSection], list[dict], list[str]]:
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
            review_required = claim_type in {"professional_explanation", "to_confirm"}
            if claim_type == "case_fact" and not _fact_preserved(text, [valid_evidence[x] for x in evidence]):
                # A valid ID proves provenance, not that a paraphrase preserves the fact.
                review_required = True
                errors.append("CASE_FACT_REQUIRES_REVIEW")
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
