"""Pure validation and version construction for REQ-06 review decisions."""

from copy import deepcopy

from .contracts.core import Insight, ReviewCorrection

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
