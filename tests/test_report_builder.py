import unittest
from copy import deepcopy
from uuid import uuid4

from services.api.app.contracts.core import Action, Report, ConsentUse
from services.api.app.report_builder import SECTION_TYPES, map_report_sources, validate_and_complete
from services.api.app.report_llm import DraftReport


class ReportBuilderTests(unittest.TestCase):
    def test_invalid_fact_reference_is_removed_and_section_discloses_gap(self):
        sections, _, errors = validate_and_complete({"sections": [{
            "section_type": "diagnosis_explanation", "claims": [{"text": "确诊肺炎",
            "claim_type": "case_fact", "evidence_refs": [str(uuid4())]}]}]}, {}, set(), {})
        self.assertIn("CASE_FACT_WITHOUT_VALID_EVIDENCE", errors)
        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[0].claims[0].claim_type, "to_confirm")

    def test_draft_knowledge_cannot_enter_professional_explanation(self):
        sections, _, errors = validate_and_complete({"sections": [{
            "section_type": "recovery_plan", "claims": [{"text": "一般知识",
            "claim_type": "professional_explanation", "knowledge_refs": ["FX-S6-01"]}]}]},
            {}, set(), {})
        self.assertIn("UNAPPROVED_KNOWLEDGE_REFERENCE", errors)

    def test_actions_are_capped_and_require_source(self):
        source = str(uuid4())
        raw = {"actions": [{"action_text": f"动作{i}", "source_refs": [source],
            "owner_role": "patient", "due_at": None, "due_source": "unknown",
            "rationale": "来自病例"} for i in range(5)]}
        _, actions, _ = validate_and_complete(raw, {source: "动作0 动作1 动作2 动作3 动作4"}, set(), {})
        self.assertEqual(len(actions), 3)
        self.assertEqual([x["priority"] for x in actions], [1, 2, 3])

    def test_report_contract_requires_all_sections(self):
        sections, _, _ = validate_and_complete({}, {}, set(), {})
        report_id = uuid4()
        report = Report(report_id=report_id, case_id=uuid4(), run_id=uuid4(), report_version=1,
            status="pending_review", sections=sections, actions=[], input_hash="a"*64,
            model_id="test", prompt_version="test", knowledge_version="test",
            policy_version="test", consent_refs=[ConsentUse(consent_id=uuid4(), version=1, purpose="case_guidance")],
            created_at="2026-09-25T00:00:00Z")
        self.assertEqual({s.section_type for s in report.sections}, set(SECTION_TYPES))

    def test_real_quote_does_not_auto_approve_contradictory_fact(self):
        source = str(uuid4())
        draft = {"sections": [{"section_type": "diagnosis_explanation", "claims": [{
            "text": "确诊肺炎", "claim_type": "case_fact", "evidence_quote": "疑似肺炎"}]}]}
        sections, _, errors = validate_and_complete(map_report_sources(draft, {source: "诊断：疑似肺炎"}),
                                                   {source: "诊断：疑似肺炎"}, set(), {})
        self.assertIn("CASE_FACT_REQUIRES_REVIEW", errors)
        self.assertEqual(sections[0].claims[0].review_status, "pending")
        self.assertEqual([str(x) for x in sections[0].claims[0].evidence_refs], [source])

    def test_substring_cannot_drop_negation_or_pending_qualifier(self):
        source = str(uuid4())
        for text in ["诊断：未见肺炎", "诊断：肺炎，待排"]:
            draft = {"sections": [{"section_type": "diagnosis_explanation", "claims": [{
                "text": "肺炎", "claim_type": "case_fact", "evidence_quote": "肺炎"}]}]}
            sections, _, errors = validate_and_complete(map_report_sources(draft, {source: text}),
                                                       {source: text}, set(), {})
            self.assertIn("CASE_FACT_REQUIRES_REVIEW", errors)
            self.assertEqual(sections[0].claims[0].review_status, "pending")

    def test_action_substring_cannot_turn_history_or_prohibition_into_instruction(self):
        source = str(uuid4())
        for context in ["不要服用阿司匹林", "既往服用阿司匹林，目前已停"]:
            _, actions, errors = validate_and_complete({'actions': [{
                'action_text': '服用阿司匹林', 'source_refs': [source],
                'due_source': 'unknown'}]}, {source: context}, set(), {})
            self.assertEqual(len(actions), 1)
            self.assertIn('ACTION_REQUIRES_REVIEW', errors)

    def test_action_contract_rejects_natural_language_or_naive_deadline(self):
        for due in ["明天", "2026-10-10", "2026-10-10T09:00:00"]:
            with self.assertRaises(ValueError):
                Action(action_id=uuid4(), report_id=uuid4(), source_refs=[str(uuid4())],
                    owner_role="patient", action_text="复诊", due_at=due,
                    due_source="medical_order", status="proposed", priority=1, rationale="遵医嘱")

    def test_verbatim_fact_keeps_assertion_and_whitespace_is_ignored(self):
        source = str(uuid4())
        draft = {"sections": [{"section_type": "diagnosis_explanation", "claims": [{
            "text": "疑似肺炎", "claim_type": "case_fact", "evidence_quote": "疑似\n肺炎"}]}]}
        evidence = {source: "诊断：疑似\n肺炎"}
        sections, _, errors = validate_and_complete(map_report_sources(draft, evidence), evidence, set(), {})
        self.assertEqual(errors, [])
        self.assertEqual(sections[0].claims[0].review_status, "not_required")

    def test_quote_mapping_preserves_auditable_model_draft(self):
        source = str(uuid4())
        draft = {"sections": [{"section_type": "diagnosis_explanation", "claims": [{
            "text": "疑似肺炎", "claim_type": "case_fact", "evidence_quote": "疑似肺炎"}]}],
            "actions": [{"action_text": "复诊", "source_quote": "复诊", "source_refs": []}]}
        original = deepcopy(draft)
        mapped = map_report_sources(draft, {source: "疑似肺炎，复诊"})
        self.assertEqual(draft, original)
        self.assertEqual(mapped["actions"][0]["source_refs"], [source])

    def test_unsafe_action_is_removed_but_prohibition_is_retained(self):
        source = str(uuid4())
        actions = [{"action_text": text, "source_refs": [source], "due_source": "unknown"}
                   for text in ["请自行停药", "不要自行停药"]]
        _, kept, errors = validate_and_complete({"actions": actions}, {source: "不要自行停药"}, set(), {})
        self.assertIn("UNSAFE_OR_EMPTY_ACTION", errors)
        self.assertEqual([action["action_text"] for action in kept], ["不要自行停药"])

    def test_user_request_cannot_be_labeled_as_medical_order(self):
        raw = {"actions": [{"action_text": "提醒我复诊", "source_refs": ["case:user_context"],
            "due_source": "medical_order", "due_at": "2026-10-10T09:00:00+08:00"}]}
        _, actions, errors = validate_and_complete(raw, {}, set(), {"case:user_context": "提醒我复诊"})
        self.assertIn("ACTION_DUE_SOURCE_MISMATCH", errors)
        self.assertIsNone(actions[0]["due_at"])
        self.assertEqual(actions[0]["due_source"], "unknown")

    def test_invented_deadline_is_removed_and_action_requires_review(self):
        source = str(uuid4())
        raw = {"actions": [{"action_text": "三天后复诊", "source_refs": [source],
            "due_source": "medical_order", "due_at": "2026-10-10T09:00:00+08:00"}]}
        _, actions, errors = validate_and_complete(raw, {source: "不适随诊"}, set(), {})
        self.assertIn("ACTION_REQUIRES_REVIEW", errors)
        self.assertIn("ACTION_DUE_REQUIRES_REVIEW", errors)
        self.assertIsNone(actions[0]["due_at"])

    def test_explicit_user_reminder_keeps_its_time_and_source(self):
        due = "2026-10-10T09:00:00+08:00"
        raw = {"actions": [{"action_text": "提醒我复诊", "source_refs": ["case:user_context"],
            "due_source": "user_request", "due_at": due}]}
        _, actions, errors = validate_and_complete(raw, {}, set(), {"case:user_context": "提醒我复诊 " + due})
        self.assertEqual(errors, [])
        self.assertEqual(actions[0]["due_at"], due)

    def test_duplicate_or_missing_draft_sections_fail_schema(self):
        sections = [{"section_type": section, "claims": []} for section in SECTION_TYPES]
        DraftReport.model_validate({"sections": sections, "actions": []})
        for invalid in [sections[:-1], [sections[0]] * 6]:
            with self.assertRaises(ValueError):
                DraftReport.model_validate({"sections": invalid, "actions": []})


if __name__ == "__main__": unittest.main()
