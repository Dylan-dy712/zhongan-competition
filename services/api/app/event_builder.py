"""Build conservative encounter events and relations from validated facts."""

from uuid import UUID, uuid4, uuid5

from .cost_breakdown import has_cost_conflicts
from .fact_extractor import UNATTRIBUTED, medication_slot


BUILDER_VERSION = "medical-event-builder-v3"
EVENT_TYPES = {
    "diagnosis": "diagnosis", "surgery": "surgery", "medication": "medication",
    "stay_days": "stay", "total_cost": "cost", "cost_breakdown":"cost",
}


def _event_time(fact, dates) -> tuple[dict | None, str]:
    """Admission/discharge dates only backfill the stay event; unresolvable dates stay null."""
    if fact["fact_type"] != "stay_days":
        return None, "unknown"
    dates = dates or {}
    admission, discharge = dates.get("admission") or {}, dates.get("discharge") or {}
    if admission.get("status") == "observed" and discharge.get("status") == "observed":
        return {"start": admission["date"], "end": discharge["date"]}, "interval"
    if admission.get("status") == "observed":
        return {"start": admission["date"]}, "day"
    if discharge.get("status") == "observed":
        return {"start": discharge["date"]}, "day"
    return None, "unknown"


def build_events(run_id: UUID, facts, encounter_dates=None):
    encounter_dates = encounter_dates or {}
    encounters: dict[str, UUID] = {}
    events, relations = [], []
    for fact in facts:
        if fact["status"] in {"missing", "unreadable", "not_applicable"}:
            continue
        encounter_key = fact.get("encounter_key") or UNATTRIBUTED
        encounter_id = encounters.setdefault(encounter_key, uuid5(run_id, f"encounter:{encounter_key}"))
        conflicted=fact['status']=='conflict' or (fact['fact_type']=='cost_breakdown' and has_cost_conflicts(fact['value']))
        representative = fact["value"]
        if representative is None and fact.get("alternatives"):
            representative = fact["alternatives"][0].get("value")
        # Event identity includes the encounter (and drug/phase for medications) so
        # one run can carry several encounters without colliding.
        event_id = uuid5(run_id, f"event:{encounter_key}:{fact['fact_type']}:{medication_slot(representative)}")
        occurred_at, time_precision = _event_time(fact, encounter_dates.get(encounter_key))
        evidence_ids = list(fact["evidence_ids"])
        if fact["status"] == "conflict":
            for alternative in fact["alternatives"]:
                evidence_ids.extend(str(item) for item in alternative["evidence_ids"])
        evidence_ids = list(dict.fromkeys(str(item) for item in evidence_ids))
        events.append({
            "event_id": event_id, "encounter_id": encounter_id,
            "event_type": EVENT_TYPES[fact["fact_type"]],
            "assertion": "unknown" if conflicted else fact["assertion"],
            "occurred_at": occurred_at, "time_precision": time_precision,
            "attributes": {
                "fact_type": fact["fact_type"], "encounter_key": encounter_key,
                "value": fact["value"],
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
    return encounters, events, relations
