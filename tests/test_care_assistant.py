import unittest
from unittest.mock import patch
from uuid import uuid4

from services.api.app.care_assistant import answer_question
from services.api.app.contracts.core import Claim, ConsentUse, Report, ReportSection


class CareAssistantTests(unittest.TestCase):
    def report(self):
        evidence_id, claim_id = uuid4(), uuid4()
        sections = []
        for section_type in ("diagnosis_explanation", "treatment_review", "cost_explanation",
                             "recovery_plan", "emotional_support", "next_visit_advice"):
            sections.append(ReportSection(section_type=section_type, claims=[Claim(
                claim_id=claim_id if not sections else uuid4(), text="已审核内容",
                claim_type="case_fact", evidence_refs=[evidence_id], review_status="not_required")]))
        return Report(report_id=uuid4(), case_id=uuid4(), run_id=uuid4(), report_version=1,
            status="published", sections=sections, actions=[], input_hash="a" * 64,
            model_id="test", prompt_version="test", knowledge_version="test", policy_version="test",
            consent_refs=[ConsentUse(consent_id=uuid4(), version=1, purpose="case_guidance")],
            created_at="2026-09-25T00:00:00Z"), claim_id, evidence_id

    @patch("services.api.app.care_assistant.OpenAiCompatibleExtractor")
    def test_unknown_citations_reject_the_whole_answer(self, extractor):
        report, claim_id, evidence_id = self.report()
        bad_claim, bad_evidence = uuid4(), uuid4()
        extractor.return_value.model_id = "deepseek"
        extractor.return_value._call.return_value = ({"model": "deepseek"},
            '{"answer":"回答","citations":[{"claim_id":"%s","evidence_refs":["%s"]},'
            '{"claim_id":"%s","evidence_refs":["%s"]}],"uncertainty":null}' %
            (claim_id, evidence_id, bad_claim, bad_evidence))
        with self.assertRaisesRegex(RuntimeError, "ASSISTANT_INVALID_CITATION"):
            answer_question(report, "问题")

    @patch("services.api.app.care_assistant.OpenAiCompatibleExtractor")
    def test_known_claim_with_foreign_evidence_rejects_answer(self, extractor):
        report, claim_id, _ = self.report()
        extractor.return_value._call.return_value = ({"model": "test"},
            '{"answer":"回答","citations":[{"claim_id":"%s","evidence_refs":["%s"]}]}' %
            (claim_id, uuid4()))
        with self.assertRaisesRegex(RuntimeError, "ASSISTANT_INVALID_CITATION"):
            answer_question(report, "问题")

    @patch("services.api.app.care_assistant.OpenAiCompatibleExtractor")
    def test_allowed_citation_keeps_answer_and_evidence(self, extractor):
        report, claim_id, evidence_id = self.report()
        extractor.return_value._call.return_value = ({"model": "test"},
            '{"answer":"回答","citations":[{"claim_id":"%s","evidence_refs":["%s"]}]}' %
            (claim_id, evidence_id))
        answer = answer_question(report, "问题")
        self.assertEqual(answer.citations[0].evidence_refs, [evidence_id])


if __name__ == "__main__":
    unittest.main()
