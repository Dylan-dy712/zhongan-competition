"""Build conservative encounter events and relations from validated facts."""

from uuid import UUID, uuid4, uuid5
from .cost_breakdown import has_cost_conflicts


BUILDER_VERSION = "medical-event-builder-v2"
EVENT_TYPES = {
    "diagnosis": "diagnosis", "surgery": "surgery", "medication": "medication",
    "stay_days": "stay", "total_cost": "cost", "cost_breakdown":"cost",
}


def build_events(run_id: UUID, facts):
    encounter_id = uuid5(run_id, "encounter:primary")
    events, relations = [], []
    for fact in facts:
        if fact["status"] in {"missing", "unreadable", "not_applicable"}:
            continue
        conflicted=fact['status']=='conflict' or (fact['fact_type']=='cost_breakdown' and has_cost_conflicts(fact['value']))
        event_id = uuid5(run_id, f"event:{fact['fact_type']}")
        evidence_ids = list(fact["evidence_ids"])
        if fact["status"] == "conflict":
            for alternative in fact["alternatives"]:
                evidence_ids.extend(str(item) for item in alternative["evidence_ids"])
        evidence_ids = list(dict.fromkeys(str(item) for item in evidence_ids))
        events.append({
            "event_id": event_id, "encounter_id": encounter_id,
            "event_type": EVENT_TYPES[fact["fact_type"]],
            "assertion": "unknown" if conflicted else fact["assertion"],
            "occurred_at": None, "time_precision": "unknown",
            "attributes": {
                "fact_type": fact["fact_type"], "value": fact["value"],
                "raw_value": fact["raw_value"], "status": fact["status"],
                "unit": fact["unit"], "alternatives": fact["alternatives"],
            },
            "evidence_ids": evidence_ids, "confidence_score": fact["confidence_score"],
            "builder_version": BUILDER_VERSION,
        })
        relations.append({
            "relation_id": uuid4(), "from_event_id": event_id,
            "relation_type": "belongs_to_encounter",
            "to_ref": {"encounter_id": str(encounter_id)},
            "evidence_ids": evidence_ids,
            "status": "indeterminate" if conflicted else "supported",
            "builder_version": BUILDER_VERSION,
        })
    return encounter_id, events, relations
