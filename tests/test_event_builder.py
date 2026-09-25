import unittest
from uuid import uuid4

from services.api.app.event_builder import build_events
from services.api.app.fact_extractor import extract_facts


class EventBuilderTests(unittest.TestCase):
    def test_builds_supported_events_without_inventing_time(self):
        evidence_id, run_id = uuid4(), uuid4()
        facts = extract_facts([{"evidence_id": evidence_id, "text": "诊断：疑似肺炎\n住院共7天"}])
        encounter_id, events, relations = build_events(run_id, facts)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event["encounter_id"] == encounter_id for event in events))
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


if __name__ == "__main__":
    unittest.main()
