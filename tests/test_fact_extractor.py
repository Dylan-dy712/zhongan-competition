import unittest
from copy import deepcopy
from uuid import uuid4

from services.api.app.fact_extractor import extract_facts, merge_model_candidates, normalize_value
from services.api.app.llm_extractor import ModelCandidate
from services.api.app.contracts.core import FieldCandidate


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

    def test_fractional_stay_preserves_rule_model_and_json_number(self):
        rows = [{'evidence_id': uuid4(), 'text': '住院天数：3.5天'}]
        model = ModelCandidate(fact_type='stay_days', raw_value='3.5天', normalized_value=3.5,
                               assertion='present', evidence_quote='住院天数：3.5天')
        rules = extract_facts(rows)
        merged = merge_model_candidates(rules, [model.model_dump()], rows)
        stay = next(f for f in merged if f['fact_type'] == 'stay_days')
        self.assertEqual(stay['value'], 3.5)
        self.assertEqual(stay['status'], 'observed')
        self.assertEqual(stay['unit'], 'day')
        self.assertEqual(normalize_value('stay_days', '3.0天'), 3)

    def test_invalid_stay_is_not_silently_truncated_or_observed(self):
        for value in ['-3.5天', '3-5天', '3.5.1天', 'NaN', 'Infinity', True]:
            self.assertIsNone(normalize_value('stay_days', value))
        rows = [{'evidence_id': uuid4(), 'text': '住院天数未记载'}]
        facts = merge_model_candidates(extract_facts(rows), [{
            'fact_type': 'stay_days', 'raw_value': '3-5天', 'normalized_value': '3-5天',
            'assertion': 'present', 'evidence_quote': '住院天数未记载'}], rows)
        self.assertEqual(next(f for f in facts if f['fact_type'] == 'stay_days')['status'], 'missing')

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

    def test_three_model_values_and_repeated_value_preserve_all_sources(self):
        rows = [{'evidence_id': uuid4(), 'text': text} for text in [
            '医疗总费用：100元', '窗口记录200元', '另一记录300元', '复核记录200元']]
        rules = extract_facts(rows)
        unchanged = deepcopy(rules)
        models = [{'fact_type': 'total_cost', 'raw_value': f'{amount}元',
            'normalized_value': {'amount_minor': amount * 100, 'currency': 'CNY'},
            'assertion': 'present', 'evidence_quote': row['text']} for amount, row in
            zip([200, 300, 200], rows[1:])]
        merged = merge_model_candidates(rules, models, rows)
        cost = next(item for item in merged if item['fact_type'] == 'total_cost')
        self.assertEqual(rules, unchanged)
        self.assertEqual(cost['status'], 'conflict')
        self.assertIsNone(cost['value'])
        self.assertEqual([a['value']['amount_minor'] for a in cost['alternatives']], [10000, 20000, 30000])
        self.assertEqual(set(cost['alternatives'][1]['evidence_ids']), {str(rows[1]['evidence_id']), str(rows[3]['evidence_id'])})
        for alternative in cost['alternatives']:
            FieldCandidate[object].model_validate(alternative)

    def test_rule_scalar_disagreements_and_duplicate_sources_are_retained(self):
        rows = [{'evidence_id': uuid4(), 'text': text} for text in [
            '医疗总费用：100元\n住院共3.5天', '医疗总费用：200元\n医疗总费用：300元\n住院共4天',
            '医疗总费用：100元\n住院共3.5天']]
        facts = {f['fact_type']: f for f in extract_facts(rows)}
        self.assertEqual(len(facts['total_cost']['alternatives']), 3)
        self.assertEqual(set(facts['total_cost']['alternatives'][0]['evidence_ids']),
                         {str(rows[0]['evidence_id']), str(rows[2]['evidence_id'])})
        self.assertEqual([a['value'] for a in facts['stay_days']['alternatives']], [3.5, 4])
        same = extract_facts([rows[0], rows[2]])
        cost = next(f for f in same if f['fact_type'] == 'total_cost')
        self.assertEqual(cost['status'], 'observed')
        self.assertEqual(len(cost['evidence_ids']), 2)

    def test_whitespace_quote_or_empty_entity_cannot_create_observed_fact(self):
        rows = [{'evidence_id': uuid4(), 'text': '未记录实体 空白'}]
        for quote, value in [(' ', '肺炎'), ('未记录实体', ' ')]:
            facts = merge_model_candidates(extract_facts(rows), [{
                'fact_type': 'diagnosis', 'raw_value': value, 'normalized_value': value,
                'assertion': 'present', 'evidence_quote': quote}], rows)
            self.assertEqual(next(f for f in facts if f['fact_type'] == 'diagnosis')['status'], 'missing')

    def test_null_conflict_alternative_is_rejected_at_contract_boundary(self):
        with self.assertRaises(ValueError):
            FieldCandidate[object](value=None, evidence_ids=[uuid4()])

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
