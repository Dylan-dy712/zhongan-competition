import unittest
from copy import deepcopy
from uuid import uuid4

from services.api.app.fact_extractor import (
    assertion_for, collect_encounter_dates, extract_facts, merge_model_candidates, normalize_value)
from services.api.app.event_builder import build_events
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

    def test_uncertain_exclusion_is_not_negated_or_confirmed(self):
        for qualifier in ['未排除', '尚未排除', '未能排除', '不能排除', '无法排除', '不除外', '待明确', '待确诊']:
            with self.subTest(qualifier=qualifier):
                facts = extract_facts([{'evidence_id': uuid4(), 'text': f'诊断：肺炎，{qualifier}'}])
                diagnosis = next(f for f in facts if f['fact_type'] == 'diagnosis')
                self.assertEqual(diagnosis['assertion'], 'suspected')
        self.assertEqual(assertion_for('诊断：已排除肺炎'), 'negated')
        self.assertEqual(assertion_for('诊断：既往肺炎'), 'historical')
        self.assertEqual(assertion_for('诊断：否认既往肺炎'), 'negated')
        self.assertEqual(assertion_for('诊断：既往肺炎，目前疑似肺炎'), 'unknown')

    def test_model_entity_quote_cannot_drop_source_qualifiers(self):
        for text, expected in [('CT提示不能排除肺炎', 'unknown'), ('病史：既往肺炎', 'unknown'),
                               ('检查提示未见肺炎', 'unknown'), ('肺炎待排', 'unknown'),
                               ('肺炎待排。此次确诊肺炎', 'unknown'), ('CT提示肺炎', 'present')]:
            with self.subTest(text=text):
                rows = [{'evidence_id': uuid4(), 'text': text}]
                facts = merge_model_candidates(extract_facts(rows), [{
                    'fact_type': 'diagnosis', 'raw_value': '肺炎', 'normalized_value': '肺炎',
                    'assertion': 'present', 'evidence_quote': '肺炎'}], rows)
                diagnosis = next(f for f in facts if f['fact_type'] == 'diagnosis')
                self.assertEqual(diagnosis['assertion'], expected)
                _, events, _ = build_events(uuid4(), facts)
                self.assertEqual(events[0]['assertion'], expected)

    def test_equal_entity_with_different_assertions_remains_unknown(self):
        # The assertion qualifier ('既往') is normalized through the assertion, so the
        # raw value keeps it while the normalized value drops it.
        rows = [{'evidence_id': uuid4(), 'text': '诊断：肺炎\n既往肺炎'}]
        facts = merge_model_candidates(extract_facts(rows), [{
            'fact_type': 'diagnosis', 'raw_value': '既往肺炎', 'normalized_value': '肺炎',
            'assertion': 'historical', 'evidence_quote': '既往肺炎'}], rows)
        diagnosis = next(f for f in facts if f['fact_type'] == 'diagnosis')
        self.assertEqual(diagnosis['value'], '肺炎')
        self.assertEqual(diagnosis['assertion'], 'unknown')

    def test_negated_and_historical_model_values_survive_strict_derivation(self):
        # P2/P3: assertion-carrying candidates only need the quote binding; the model
        # may drop the qualifier from normalized_value because the assertion carries it.
        for fact_type, raw, assertion, value in [
                ('diagnosis', '否认高血压病史', 'negated', '高血压'),
                ('surgery', '2019年曾行阑尾切除术', 'historical', '阑尾切除术')]:
            with self.subTest(raw=raw):
                rows = [{'evidence_id': uuid4(), 'text': raw}]
                merged = merge_model_candidates(extract_facts(rows), [{
                    'fact_type': fact_type, 'raw_value': raw, 'normalized_value': value,
                    'assertion': assertion, 'evidence_quote': raw}], rows)
                fact = next(f for f in merged if f['fact_type'] == fact_type)
                self.assertEqual(fact['status'], 'observed')
                self.assertEqual(fact['value'], value)
                self.assertEqual(fact['assertion'], assertion)

    def test_unbound_present_value_still_requires_derivation(self):
        # The present-tense derivability guard keeps the model's invented value out;
        # the rule-documented value stays the standing fact.
        rows = [{'evidence_id': uuid4(), 'text': '诊断：肺炎'}]
        merged = merge_model_candidates(extract_facts(rows), [{
            'fact_type': 'diagnosis', 'raw_value': '肺炎', 'normalized_value': '肺部感染',
            'assertion': 'present', 'evidence_quote': '诊断：肺炎'}], rows)
        diagnosis = next(f for f in merged if f['fact_type'] == 'diagnosis')
        self.assertEqual(diagnosis['status'], 'observed')
        self.assertEqual(diagnosis['value'], '肺炎')
        self.assertNotIn('肺部感染', str(diagnosis['alternatives']))

    def test_self_reported_assertion_is_no_licence_for_unbound_values(self):
        # The model can fabricate its own assertion: an entity that appears nowhere in
        # the quote or its page is dropped even under a claimed negated assertion.
        rows = [{'evidence_id': uuid4(), 'text': '复查记录：肺炎恢复良好'}]
        merged = merge_model_candidates(extract_facts(rows), [{
            'fact_type': 'diagnosis', 'raw_value': '肺炎恢复良好',
            'normalized_value': '急性胰腺炎', 'assertion': 'negated',
            'evidence_quote': '复查记录：肺炎恢复良好'}], rows)
        diagnosis = next(f for f in merged if f['fact_type'] == 'diagnosis')
        self.assertEqual(diagnosis['status'], 'missing')
        self.assertEqual(diagnosis['missing_reason'], 'not_documented_in_parsed_materials')

    def test_qualifier_fabrication_on_a_present_sentence_is_corrected(self):
        # A genuine entity whose cited sentence is present-tense cannot be flipped to
        # negated/suspected/historical by the model's own assertion claim.
        rows = [{'evidence_id': uuid4(), 'text': '复查记录：肺炎恢复良好'}]
        merged = merge_model_candidates(extract_facts(rows), [{
            'fact_type': 'diagnosis', 'raw_value': '肺炎恢复良好', 'normalized_value': '肺炎',
            'assertion': 'negated', 'evidence_quote': '复查记录：肺炎恢复良好'}], rows)
        diagnosis = next(f for f in merged if f['fact_type'] == 'diagnosis')
        self.assertEqual(diagnosis['status'], 'observed')
        self.assertEqual(diagnosis['assertion'], 'present')

    def test_admission_and_discharge_progression_stays_observed_not_conflict(self):
        # P1: 入院/出院诊断 wording progression inside one visit is clinically normal;
        # a conflict fact here would hard-block releases with no resolution channel.
        rows = [{"evidence_id": "G1", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "入院诊断：子宫平滑肌瘤\n出院诊断：子宫平滑肌瘤伴贫血"}]
        diagnoses = [item for item in extract_facts(rows) if item["fact_type"] == "diagnosis"]
        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["status"], "observed")
        self.assertEqual(diagnoses[0]["value"], "子宫平滑肌瘤")
        self.assertEqual(diagnoses[0]["alternatives"], [])

    def test_repeated_same_value_within_encounter_accumulates_evidence(self):
        rows = [{"evidence_id": "H1", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "入院诊断：子宫平滑肌瘤"},
                {"evidence_id": "H2", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "出院诊断：子宫平滑肌瘤"}]
        diagnoses = [item for item in extract_facts(rows) if item["fact_type"] == "diagnosis"]
        self.assertEqual(len(diagnoses), 1)
        self.assertEqual(diagnoses[0]["status"], "observed")
        self.assertEqual(set(diagnoses[0]["evidence_ids"]), {"H1", "H2"})

    def test_amounts_never_vote_in_case_year_mode(self):
        # P4: '2000元' is an amount, not a year; it must not flip the case year mode.
        rows = [{"evidence_id": f"F{i}", "encounter_key": "encounter:inpatient:2025-11-07",
                 "text": text} for i, text in enumerate([
                    "押金2000元\n手术名称：2025-11-08右眼白内障超声乳化摘除术",
                    "自费2000元", "费用2000元"])]
        surgery = next(item for item in extract_facts(rows) if item["fact_type"] == "surgery")
        self.assertEqual(surgery["status"], "observed")
        self.assertEqual(surgery["value"], "2025-11-08右眼白内障超声乳化摘除术")

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
        rows = [{"evidence_id": evidence_id, "text": "诊断：肺炎\n复查记录：肺部感染"}]
        rules = extract_facts(rows)
        merged = {item["fact_type"]: item for item in merge_model_candidates(rules, [{
            "fact_type": "diagnosis", "raw_value": "肺部感染", "normalized_value": "肺部感染",
            "assertion": "present", "evidence_quote": "复查记录：肺部感染", "confidence_score": 0.8,
        }], rows)}
        self.assertEqual(merged["diagnosis"]["status"], "conflict")
        self.assertIsNone(merged["diagnosis"]["value"])
        self.assertEqual(len(merged["diagnosis"]["alternatives"]), 2)

    def test_model_value_unbound_to_quote_or_source_is_dropped(self):
        # The model asserts a value its own quote never contains: zero source binding.
        evidence_id = uuid4()
        rows = [{"evidence_id": evidence_id, "text": "术后医嘱：妥布霉素地塞米松滴眼液"}]
        merged = merge_model_candidates(extract_facts(rows), [{
            "fact_type": "medication", "raw_value": "妥布霉素地塞米松滴眼液（出院时间2020-11-08）",
            "normalized_value": "妥布霉素地塞米松滴眼液（出院时间2020-11-08）",
            "assertion": "present", "evidence_quote": "术后医嘱：妥布霉素地塞米松滴眼液",
            "confidence_score": 0.9,
        }], rows)
        medication = next(item for item in merged if item["fact_type"] == "medication")
        self.assertEqual(medication["status"], "missing")

    def test_three_model_values_and_repeated_value_preserve_all_sources(self):
        rows = [{'evidence_id': uuid4(), 'text': text} for text in [
            '医疗总费用：100元', '窗口记录：总费用：200元', '另一记录：总费用：300元', '复核记录：总费用：200元']]
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

    def test_off_century_year_is_conservatively_missing_with_trace(self):
        # CL0300004731865852 shape: a century-flipped OCR year must not enter as observed.
        rows = [{"evidence_id": "E1", "encounter_key": "encounter:inpatient:2025-11-07",
                 "text": "手术名称：2020-11-08右眼白内障超声乳化摘除+人工晶体植入术"},
                {"evidence_id": "E2", "encounter_key": "encounter:inpatient:2025-11-07",
                 "text": "入院时间：2025-11-07\n出院时间：2025-11-08 09:20"}]
        facts = {item["fact_type"]: item for item in extract_facts(rows)}
        surgery = facts["surgery"]
        self.assertEqual(surgery["status"], "missing")
        self.assertEqual(surgery["missing_reason"], "year_unresolvable")
        self.assertIsNone(surgery["value"])
        self.assertIn("2020-11-08", surgery["raw_value"])
        self.assertEqual(surgery["evidence_ids"], ["E1"])

    def test_two_digit_years_are_window_expanded_and_historical_years_survive(self):
        self.assertEqual(normalize_value("surgery", "25-11-25阑尾切除术"), "2025-11-25阑尾切除术")
        rows = [{"evidence_id": "E1", "encounter_key": "encounter:inpatient:2025-11-07",
                 "text": "手术名称：2019年曾行阑尾切除术\n入院时间：2025-11-07"}]
        surgery = next(item for item in extract_facts(rows) if item["fact_type"] == "surgery")
        # A historical assertion carries its own timeframe and is not year-gated.
        self.assertEqual(surgery["assertion"], "historical")
        self.assertEqual(surgery["status"], "observed")

    def test_same_month_day_conflicting_discharge_years_stay_visible(self):
        rows = [{"evidence_id": "A", "encounter_key": "encounter:inpatient:2025-11-07",
                 "text": "出院时间：2020-11-08 09:20"},
                {"evidence_id": "B", "encounter_key": "encounter:inpatient:2025-11-07",
                 "text": "出院时间：2025-11-08 09:20"}]
        dates = collect_encounter_dates(rows)
        discharge = dates["encounter:inpatient:2025-11-07"]["discharge"]
        # Same month-day/hour across pages: both years stay traceable, none is picked.
        self.assertEqual(discharge["status"], "conflict")
        self.assertIsNone(discharge["date"])
        self.assertEqual(discharge["alternatives"], ["2020-11-08", "2025-11-08"])
        # With a third page the case mode resolves the flipped century conservatively.
        rows.append({"evidence_id": "C", "encounter_key": "encounter:inpatient:2025-11-07",
                     "text": "入院时间：2025-11-07"})
        resolved = collect_encounter_dates(rows)["encounter:inpatient:2025-11-07"]
        self.assertEqual(resolved["discharge"]["status"], "observed")
        self.assertEqual(resolved["discharge"]["date"], "2025-11-08")
        self.assertEqual(resolved["discharge"]["unresolved"], [2020])

    def test_encounter_scoped_labels_keep_each_visit_separate(self):
        # CL0300004727437832 shape: outpatient and inpatient diagnoses are distinct facts.
        rows = [{"evidence_id": "EV4", "encounter_key": "encounter:outpatient:2025-07-19",
                 "text": "诊断：1、子宫平滑肌瘤D25.900"},
                {"evidence_id": "EV7", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "入院诊断：1、子宫平滑肌瘤"}]
        diagnoses = [item for item in extract_facts(rows) if item["fact_type"] == "diagnosis"]
        self.assertEqual(len(diagnoses), 2)
        self.assertEqual({item["encounter_key"] for item in diagnoses},
                         {"encounter:outpatient:2025-07-19", "encounter:inpatient:2025-07-28"})
        self.assertTrue(all(item["status"] == "observed" for item in diagnoses))

    def test_pages_without_dates_stay_unattributed_never_primary(self):
        rows = [{"evidence_id": "E1", "text": "住院共14天"}]
        facts = extract_facts(rows)
        stay = next(item for item in facts if item["fact_type"] == "stay_days")
        self.assertEqual(stay["encounter_key"], "encounter:unattributed")
        self.assertEqual(stay["status"], "observed")

    def test_discharge_and_plan_drugs_coexist_instead_of_collapsing(self):
        rows = [{"evidence_id": "M2", "encounter_key": "encounter:outpatient:2025-07-19",
                 "text": "用药：醋酸戈舍瑞林缓释植入剂，下次复诊行第2针"},
                {"evidence_id": "M3", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "出院带药：益气维血片"},
                {"evidence_id": "M4", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "用药：阿莫西林"}]
        medications = [item for item in extract_facts(rows) if item["fact_type"] == "medication"]
        by_phase = {item["value"]["phase"]: item for item in medications}
        self.assertEqual(by_phase["plan"]["value"]["drug_name"], "醋酸戈舍瑞林缓释植入剂，下次复诊行第2针")
        self.assertEqual(by_phase["discharge"]["value"]["drug_name"], "益气维血片")
        self.assertEqual(by_phase["unknown"]["value"]["drug_name"], "阿莫西林")
        # Three (drug, phase) slots stay independent observed facts, never one conflict.
        self.assertEqual(len(medications), 3)
        self.assertTrue(all(item["status"] == "observed" for item in medications))

    def test_medication_candidate_phase_is_inferred_from_its_own_quote(self):
        rows = [{"evidence_id": "M2", "encounter_key": "encounter:outpatient:2025-07-19",
                 "text": "诊疗意见：28天后复诊行第2针GN治疗。醋酸戈舍瑞林缓释植入剂（3.6mg）1支"}]
        merged = merge_model_candidates(extract_facts(rows), [{
            "fact_type": "medication", "raw_value": "醋酸戈舍瑞林缓释植入剂（3.6mg）1支",
            "normalized_value": "醋酸戈舍瑞林缓释植入剂", "drug_name": "醋酸戈舍瑞林缓释植入剂",
            "dose": "3.6mg", "assertion": "present",
            "evidence_quote": "28天后复诊行第2针GN治疗。醋酸戈舍瑞林缓释植入剂（3.6mg）1支",
            "confidence_score": 0.8,
        }], rows)
        medication = next(item for item in merged if item["fact_type"] == "medication")
        self.assertEqual(medication["status"], "observed")
        self.assertEqual(medication["value"]["phase"], "plan")
        self.assertEqual(medication["value"]["dose"], "3.6mg")
        self.assertEqual(medication["value"]["route"], None)

    def test_medication_label_regex_captures_second_page_instead_of_dropping(self):
        rows = [{"evidence_id": "D1", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "出院带药：益气维血片"},
                {"evidence_id": "D2", "encounter_key": "encounter:inpatient:2025-07-28",
                 "text": "出院带药：益气维血片"}]
        medications = [item for item in extract_facts(rows) if item["fact_type"] == "medication"]
        self.assertEqual(len(medications), 1)
        self.assertEqual(medications[0]["status"], "observed")
        self.assertEqual(set(medications[0]["evidence_ids"]), {"D1", "D2"})


if __name__ == "__main__":
    unittest.main()


class CostSourceGuardTests(unittest.TestCase):
    def test_subtotals_and_payments_are_not_case_totals(self):
        rows=[{'evidence_id':uuid4(),'text':'药品费：100元；明细合计：900元；现金支付：50元；合计：50元'}]
        total=next(f for f in extract_facts(rows) if f['fact_type']=='total_cost')
        self.assertEqual(total['status'],'missing')
        rows[0]['text']='医疗总费用：1000元；明细合计：900元'
        total=next(f for f in extract_facts(rows) if f['fact_type']=='total_cost')
        self.assertEqual(total['value']['amount_minor'],100000)
        self.assertEqual(total['status'],'observed')

    def test_model_cannot_invent_amount_or_promote_estimate_or_subtotal(self):
        for text,value,quote in [('医疗总费用：100元',99900,'医疗总费用：100元'),
            ('明细合计：100元',10000,'明细合计：100元'),
            ('预计医疗总费用：100元',10000,'医疗总费用：100元'),
            ('医疗总费用：100元至200元',10000,'医疗总费用：100元')]:
            rows=[{'evidence_id':uuid4(),'text':text}]
            rules=extract_facts(rows)
            result=merge_model_candidates(rules,[{'fact_type':'total_cost','raw_value':'fake raw',
                'normalized_value':{'amount_minor':value,'currency':'CNY'},'assertion':'present','evidence_quote':quote}],rows)
            total=next(f for f in result if f['fact_type']=='total_cost')
            self.assertEqual(total,next(f for f in rules if f['fact_type']=='total_cost'))
        for invalid in (True,-1,float('nan'),'1,00','3.141元','-10元','1e3元',
            {'amount_minor':True,'currency':'CNY'},{'amount_minor':1.9,'currency':'CNY'},
            {'amount_minor':-1,'currency':'CNY'},{'amount_minor':10,'currency':'USD'}):
            self.assertIsNone(normalize_value('total_cost',invalid))
