import unittest
from uuid import uuid4

from services.api.app.fact_extractor import extract_facts, merge_model_candidates


class FactExtractorTests(unittest.TestCase):
    def test_extracts_five_evidence_bound_fields(self):
        evidence_id = uuid4()
        text = "诊断：疑似肺炎\n手术：阑尾切除术\n用药：阿莫西林\n住院共7天\n医疗总费用：1,234.56元"
        facts = {item["fact_type"]: item for item in extract_facts([{"evidence_id": evidence_id, "text": text}])}
        self.assertEqual(facts["diagnosis"]["assertion"], "suspected")
        self.assertEqual(facts["diagnosis"]["value"], "肺炎")
        self.assertEqual(facts["stay_days"]["value"], 7)
        self.assertEqual(facts["total_cost"]["value"]["amount_minor"], 123456)
        self.assertTrue(all(item["evidence_ids"] for item in facts.values()))

    def test_absent_fields_are_explicitly_missing(self):
        facts = extract_facts([])
        self.assertEqual(len(facts), 5)
        self.assertTrue(all(item["status"] == "missing" for item in facts))
        self.assertTrue(all(item["missing_reason"] for item in facts))

    def test_rule_model_disagreement_remains_conflict(self):
        evidence_id = uuid4()
        rows = [{"evidence_id": evidence_id, "text": "诊断：肺炎"}]
        rules = extract_facts(rows)
        merged = {item["fact_type"]: item for item in merge_model_candidates(rules, [{
            "fact_type": "diagnosis", "raw_value": "肺部感染", "normalized_value": "肺部感染",
            "assertion": "present", "evidence_quote": "诊断：肺炎", "confidence_score": 0.8,
        }], rows)}
        self.assertEqual(merged["diagnosis"]["status"], "conflict")
        self.assertIsNone(merged["diagnosis"]["value"])
        self.assertEqual(len(merged["diagnosis"]["alternatives"]), 2)

    def test_model_cost_string_normalizes_to_minor_units(self):
        evidence_id = uuid4()
        rows = [{"evidence_id": evidence_id, "text": "医疗总费用：1,234.56元"}]
        rules = extract_facts(rows)
        merged = {item["fact_type"]: item for item in merge_model_candidates(rules, [{
            "fact_type": "total_cost", "raw_value": "1,234.56元", "normalized_value": "1234.56 CNY",
            "assertion": "present", "evidence_quote": "医疗总费用：1,234.56元", "confidence_score": 0.9,
        }], rows)}
        self.assertEqual(merged["total_cost"]["status"], "observed")


if __name__ == "__main__":
    unittest.main()
