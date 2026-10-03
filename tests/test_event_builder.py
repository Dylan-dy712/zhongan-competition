import unittest
from uuid import uuid4

from services.api.app.event_builder import build_events
from services.api.app.fact_extractor import collect_encounter_dates, extract_facts


def _dates(admission=None, discharge=None, admission_status="observed", discharge_status="observed"):
    return {"admission": ({"status": admission_status, "date": admission,
                           "alternatives": [], "evidence_ids": ["E1"]} if admission
                          else {"status": "missing", "date": None, "alternatives": [], "evidence_ids": []}),
            "discharge": ({"status": discharge_status, "date": discharge,
                           "alternatives": [], "evidence_ids": ["E1"]} if discharge
                          else {"status": "missing", "date": None, "alternatives": [], "evidence_ids": []})}


class EventBuilderTests(unittest.TestCase):
    def test_builds_supported_events_without_inventing_time(self):
        evidence_id, run_id = uuid4(), uuid4()
        facts = extract_facts([{"evidence_id": evidence_id, "text": "诊断：疑似肺炎\n住院共7天"}])
        encounters, events, relations = build_events(run_id, facts)
        self.assertEqual(len(encounters), 1)
        self.assertTrue(all(event["encounter_id"] == next(iter(encounters.values())) for event in events))
        self.assertTrue(all(event["occurred_at"] is None for event in events))
        self.assertTrue(all(event["time_precision"] == "unknown" for event in events))
        diagnosis = next(event for event in events if event["event_type"] == "diagnosis")
        self.assertEqual(diagnosis["assertion"], "suspected")
        self.assertTrue(all(relation["status"] == "supported" for relation in relations))

    def test_conflict_relation_is_indeterminate(self):
        run_id, evidence_a, evidence_b = uuid4(), uuid4(), uuid4()
        facts = [{
            "fact_type": "diagnosis", "value": None, "raw_value": None,
            "status": "conflict", "assertion": "unknown", "evidence_ids": [],
            "confidence_score": None, "unit": None,
            "alternatives": [
                {"value": "肺炎", "evidence_ids": [str(evidence_a)]},
                {"value": "支气管炎", "evidence_ids": [str(evidence_b)]},
            ],
        }]
        _, events, relations = build_events(run_id, facts)
        self.assertEqual(events[0]["assertion"], "unknown")
        self.assertEqual(relations[0]["status"], "indeterminate")
        self.assertEqual(len(events[0]["evidence_ids"]), 2)

    def test_each_visit_gets_its_own_encounter_and_events(self):
        run_id = uuid4()
        facts = extract_facts([
            {"evidence_id": "EV4", "encounter_key": "encounter:outpatient:2025-07-19",
             "text": "诊断：乳腺增生"},
            {"evidence_id": "EV7", "encounter_key": "encounter:inpatient:2025-07-28",
             "text": "入院诊断：子宫平滑肌瘤"},
        ])
        encounters, events, relations = build_events(run_id, facts)
        self.assertEqual(len(encounters), 2)
        by_encounter = {event["attributes"]["encounter_key"]: event["encounter_id"] for event in events}
        self.assertEqual(len(events), 2)
        self.assertEqual(len({str(value) for value in encounters.values()}), 2)
        for key, encounter_id in encounters.items():
            self.assertEqual(by_encounter[key], encounter_id)
            self.assertTrue(all(relation["to_ref"] == {"encounter_id": str(encounter_id)}
                                for relation in relations
                                if relation["from_event_id"] in
                                {event["event_id"] for event in events
                                 if event["encounter_id"] == encounter_id}))

    def test_normalized_stay_dates_backfill_event_time(self):
        run_id = uuid4()
        key = "encounter:inpatient:2025-07-28"
        facts = extract_facts([{"evidence_id": "E1", "encounter_key": key, "text": "住院共14天"}])
        encounters, events, _relations = build_events(run_id, facts, {key: _dates("2025-07-28", "2025-08-11")})
        stay = next(event for event in events if event["event_type"] == "stay")
        self.assertEqual(stay["occurred_at"], {"start": "2025-07-28", "end": "2025-08-11"})
        self.assertEqual(stay["time_precision"], "interval")

    def test_conflicted_dates_never_backfill_event_time(self):
        run_id = uuid4()
        key = "encounter:inpatient:2025-11-07"
        facts = extract_facts([{"evidence_id": "E1", "encounter_key": key, "text": "住院共1天"}])
        dates = {key: _dates("2025-11-08", None, discharge_status="conflict")}
        dates[key]["discharge"]["alternatives"] = ["2020-11-08", "2025-11-08"]
        _encounters, events, _relations = build_events(run_id, facts, dates)
        stay = next(event for event in events if event["event_type"] == "stay")
        self.assertEqual(stay["occurred_at"], {"start": "2025-11-08"})
        self.assertEqual(stay["time_precision"], "day")

    def test_medication_events_of_one_visit_do_not_collide(self):
        run_id = uuid4()
        key = "encounter:inpatient:2025-07-28"
        facts = extract_facts([
            {"evidence_id": "M1", "encounter_key": key, "text": "出院带药：益气维血片"},
            {"evidence_id": "M2", "encounter_key": key, "text": "带药：头孢呋辛"},
        ])
        _encounters, events, relations = build_events(run_id, facts)
        medications = [event for event in events if event["event_type"] == "medication"]
        self.assertEqual(len(medications), 2)
        self.assertEqual(len({str(event["event_id"]) for event in medications}), 2)
        self.assertEqual(len(relations), 2)

    def test_real_collected_dates_drive_event_time_including_unresolved(self):
        # Wire collect_encounter_dates' real output — including its 'unresolved' key —
        # straight into build_events the way worker.process_run does.
        run_id = uuid4()
        rows = [
            {"evidence_id": "A", "encounter_key": "encounter:inpatient:2025-07-28",
             "text": "入院时间：2025-07-28\n出院时间：2025-08-11\n住院共14天"},
            {"evidence_id": "B", "encounter_key": "encounter:inpatient:2025-11-07",
             "text": "出院时间：2020-11-08 09:20"},
            {"evidence_id": "C", "encounter_key": "encounter:inpatient:2025-11-07",
             "text": "出院时间：2025-11-08 09:20"},
        ]
        dates = collect_encounter_dates(rows)
        self.assertIn("unresolved", dates["encounter:inpatient:2025-11-07"]["discharge"])
        facts = extract_facts(rows)
        encounters, events, _relations = build_events(run_id, facts, dates)
        stay = next(event for event in events if event["event_type"] == "stay"
                    and event["attributes"]["encounter_key"] == "encounter:inpatient:2025-07-28")
        self.assertEqual(stay["occurred_at"], {"start": "2025-07-28", "end": "2025-08-11"})
        self.assertEqual(stay["time_precision"], "interval")
        # The July stay keeps its admission/discharge interval; the November encounter
        # has conflicting discharge dates, so its stay facts carry no invented time.
        november = [event for event in events
                    if event["attributes"]["encounter_key"] == "encounter:inpatient:2025-11-07"]
        self.assertTrue(all(event["occurred_at"] is None for event in november))


if __name__ == "__main__":
    unittest.main()
