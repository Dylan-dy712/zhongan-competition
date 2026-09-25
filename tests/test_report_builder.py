import unittest
from uuid import uuid4

from services.api.app.contracts.core import Action, Report, ConsentUse
from services.api.app.report_builder import SECTION_TYPES, validate_and_complete


class ReportBuilderTests(unittest.TestCase):
    def test_invalid_fact_reference_is_removed_and_section_discloses_gap(self):
        sections, _, errors = validate_and_complete({"sections": [{
            "section_type": "diagnosis_explanation", "claims": [{"text": "确诊肺炎",
            "claim_type": "case_fact", "evidence_refs": [str(uuid4())]}]}]}, set(), set(), set())
        self.assertIn("CASE_FACT_WITHOUT_VALID_EVIDENCE", errors)
        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[0].claims[0].claim_type, "to_confirm")

    def test_draft_knowledge_cannot_enter_professional_explanation(self):
        sections, _, errors = validate_and_complete({"sections": [{
            "section_type": "recovery_plan", "claims": [{"text": "一般知识",
            "claim_type": "professional_explanation", "knowledge_refs": ["FX-S6-01"]}]}]},
            set(), set(), set())
        self.assertIn("UNAPPROVED_KNOWLEDGE_REFERENCE", errors)

    def test_actions_are_capped_and_require_source(self):
        source = str(uuid4())
        raw = {"actions": [{"action_text": f"动作{i}", "source_refs": [source],
            "owner_role": "patient", "due_at": None, "due_source": "unknown",
            "rationale": "来自病例"} for i in range(5)]}
        _, actions, _ = validate_and_complete(raw, {source}, set(), set())
        self.assertEqual(len(actions), 3)
        self.assertEqual([x["priority"] for x in actions], [1, 2, 3])

    def test_report_contract_requires_all_sections(self):
        sections, _, _ = validate_and_complete({}, set(), set(), set())
        report_id = uuid4()
        report = Report(report_id=report_id, case_id=uuid4(), run_id=uuid4(), report_version=1,
            status="pending_review", sections=sections, actions=[], input_hash="a"*64,
            model_id="test", prompt_version="test", knowledge_version="test",
            policy_version="test", consent_refs=[ConsentUse(consent_id=uuid4(), version=1, purpose="case_guidance")],
            created_at="2026-09-25T00:00:00Z")
        self.assertEqual({s.section_type for s in report.sections}, set(SECTION_TYPES))


if __name__ == "__main__": unittest.main()
