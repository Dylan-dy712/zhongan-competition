"""REQ-07 report validation and conservative section completion."""

import re
from uuid import UUID, uuid4

from .contracts.core import Claim, ReportSection

SECTION_TYPES = ("diagnosis_explanation", "treatment_review", "cost_explanation",
                 "recovery_plan", "emotional_support", "next_visit_advice")
POLICY_VERSION = "report-safety-v1"
UNSAFE_PATTERNS = (r"自行(?:停药|换药|加药)", r"保证(?:治愈|康复|有效)", r"医生(?:开错|误诊)")


def validate_and_complete(draft: dict, valid_evidence: set[str], approved_knowledge: set[str],
                          valid_source_refs: set[str]) -> tuple[list[ReportSection], list[dict], list[str]]:
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
            if not text or any(re.search(p, text) for p in UNSAFE_PATTERNS):
                errors.append("UNSAFE_OR_EMPTY_CLAIM"); continue
            try:
                claims.append(Claim(claim_id=uuid4(), text=text, claim_type=claim_type,
                    evidence_refs=evidence, knowledge_refs=knowledge, source_refs=sources,
                    review_status="pending" if claim_type in {"professional_explanation", "to_confirm"} else "not_required"))
            except Exception:
                errors.append("INVALID_CLAIM")
        if not claims:
            claims = [Claim(claim_id=uuid4(), text="当前材料不足，相关内容需要结合原始医嘱或由专业人员进一步确认。",
                            claim_type="to_confirm", review_status="pending")]
        sections.append(ReportSection(section_type=section_type, claims=claims))
    actions = []
    for raw in draft.get("actions", [])[:3]:
        refs = [x for x in raw.get("source_refs", []) if x in valid_evidence or x in valid_source_refs]
        if not refs:
            errors.append("ACTION_WITHOUT_SOURCE"); continue
        due_at, due_source = raw.get("due_at"), raw.get("due_source", "unknown")
        if due_at and due_source == "unknown":
            errors.append("ACTION_DUE_WITHOUT_SOURCE"); due_at = None
        actions.append({**raw, "source_refs": refs, "due_at": due_at,
                        "due_source": due_source, "priority": len(actions) + 1})
    return sections, actions, list(dict.fromkeys(errors))
