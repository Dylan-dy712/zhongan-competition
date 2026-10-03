"""Pure validation and version construction for REQ-06 review decisions."""

from copy import deepcopy

from uuid import uuid4

from .contracts.core import Action, Insight, Report, ReviewCorrection
from .report_builder import validate_and_complete
from .contracts.knowledge import DiseaseCode
from .insight_detector import infer_disease_code
from .knowledge_assembler import KnowledgeAssembler, KnowledgeAssemblerError

CORRECTABLE_FIELDS = {
    "severity", "rationale", "uncertainty", "suggested_action",
    "judgment_status", "knowledge_refs",
}


def corrected_insight_payload(current: Insight, corrections: list[ReviewCorrection],
                              valid_evidence_ids: set[str]) -> dict:
    if not corrections:
        raise ValueError("correct decision requires corrections")
    payload = deepcopy(current.model_dump(mode="json"))
    seen = set()
    for correction in corrections:
        field = correction.field_or_claim_id
        if field not in CORRECTABLE_FIELDS or field in seen:
            raise ValueError("invalid or duplicate correction field")
        if any(str(ref) not in valid_evidence_ids for ref in correction.source_refs):
            raise ValueError("correction source_ref is outside target run")
        seen.add(field)
        payload[field] = correction.replacement
        payload["evidence_ids"] = list(dict.fromkeys(
            payload["evidence_ids"] + [str(ref) for ref in correction.source_refs]
        ))
    payload["review_required"] = False
    payload["review_status"] = "corrected"
    return Insight.model_validate(payload).model_dump(mode="json")


REVIEWABLE_REPORT_ERRORS = {'CASE_FACT_REQUIRES_REVIEW', 'ACTION_REQUIRES_REVIEW',
                            'PATIENT_STATEMENT_REQUIRES_REVIEW', 'SERVICE_SUGGESTION_REQUIRES_REVIEW'}


def checked_report_content(current: Report, corrections: list[ReviewCorrection],
                           evidence: dict[str, str], sources: dict[str, str],
                           structured_dates: dict | None = None):
    """Re-run existing report guards; corrections cannot grant new source permissions."""
    payload = deepcopy(current.model_dump(mode='json'))
    seen = set()
    for correction in corrections:
        field = correction.field_or_claim_id
        if field not in {'sections', 'actions'} or field in seen:
            raise ValueError('invalid or duplicate report correction field')
        if any(str(ref) not in evidence for ref in correction.source_refs):
            raise ValueError('correction source_ref is outside target run')
        seen.add(field)
        payload[field] = correction.replacement
    # Validate the caller's exact content before permissive draft completion.
    payload = Report.model_validate(payload).model_dump(mode='json')
    for action in payload['actions']:
        if (action['report_id'] != str(current.report_id) or action['status'] != 'proposed' or
            action.get('feedback_ref') is not None):
            raise ValueError('review cannot import action identity or execution state')
    knowledge = {ref for section in current.sections for claim in section.claims for ref in claim.knowledge_refs}
    sections, actions, errors = validate_and_complete(payload, evidence, knowledge, sources,
                                                      structured_dates=structured_dates)
    if len(actions) != len(payload['actions']) or errors and set(errors) - REVIEWABLE_REPORT_ERRORS:
        raise ValueError('report content failed safety or source validation')
    # A filtered unknown reference must not survive through a second valid reference.
    for section in payload['sections']:
        for claim in section['claims']:
            if (any(str(ref) not in evidence for ref in claim.get('evidence_refs', [])) or
                any(ref not in knowledge for ref in claim.get('knowledge_refs', [])) or
                any(ref not in sources for ref in claim.get('source_refs', []))):
                raise ValueError('report claim reference is outside approved scope')
    for action in payload['actions']:
        if any(ref not in evidence and ref not in sources for ref in action['source_refs']):
            raise ValueError('report action reference is outside approved scope')
    return [s.model_dump(mode='json') for s in sections], actions, errors


def corrected_report_payload(current: Report, corrections: list[ReviewCorrection],
                             evidence: dict[str, str], sources: dict[str, str],
                             report_id, version: int,
                             structured_dates: dict | None = None) -> dict:
    if not corrections:
        raise ValueError('correct decision requires corrections')
    sections, action_drafts, errors = checked_report_content(current, corrections, evidence, sources,
                                                             structured_dates=structured_dates)
    payload = current.model_dump(mode='json')
    actions = [Action(action_id=uuid4(), report_id=report_id,
        **{key: item[key] for key in ('source_refs', 'owner_role', 'action_text', 'due_at',
           'due_source', 'status', 'feedback_ref', 'priority', 'rationale')}).model_dump(mode='json')
        for item in action_drafts]
    payload.update(report_id=str(report_id), report_version=version, status='pending_review',
                   sections=sections, actions=actions, validation_errors=errors)
    return Report.model_validate(payload).model_dump(mode='json')


def check_report_knowledge(report, material):
    refs = {ref for section in report.sections for claim in section.claims for ref in claim.knowledge_refs}
    if report.knowledge_version=='knowledge:none' and not refs:
        return
    try:
        assembler = KnowledgeAssembler()
        if assembler.knowledge_version!=report.knowledge_version:
            raise ValueError('knowledge version changed; regenerate and review')
        disease = infer_disease_code(material)
        allowed = set()
        for code in ({disease, DiseaseCode.ty} if disease else {DiseaseCode.ty}):
            assembler.check_exclusions(code, material)
            allowed.update(e.entry_id for e in assembler.select(code,patient_visible=True).allowed
                           if not e.numeric_pending_review)
        if not refs.issubset(allowed):
            raise ValueError('knowledge is unapproved, pending or outside case scope')
    except KnowledgeAssemblerError:
        raise ValueError('knowledge validation unavailable or case excluded') from None
