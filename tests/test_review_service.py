import unittest
from uuid import uuid4

from pydantic import ValidationError

from services.api.app.contracts.core import Insight, ReviewCorrection
from services.api.app.review_service import corrected_insight_payload


def clinical_insight():
    return Insight(
        insight_id=uuid4(), case_id=uuid4(), run_id=uuid4(), category="clinical",
        label="CLIN_MEDICATION_CONTEXT_REVIEW", severity="undetermined",
        evidence_ids=[uuid4()], rationale="自动候选", uncertainty="尚待复核",
        suggested_action="请医学审核", review_required=True, review_status="pending",
        judgment_status="candidate", rule_version="insight-rules-v1",
    )


class ReviewServiceTests(unittest.TestCase):
    def test_correction_creates_valid_reviewed_payload_without_overwriting_input(self):
        original = clinical_insight()
        source = uuid4()
        correction = ReviewCorrection(field_or_claim_id="severity", replacement="medium",
                                      source_refs=[source], reason="结合补充证据")
        payload = corrected_insight_payload(original, [correction], {str(source)})
        self.assertEqual(payload["severity"], "medium")
        self.assertEqual(payload["review_status"], "corrected")
        self.assertFalse(payload["review_required"])
        self.assertIn(str(source), payload["evidence_ids"])
        self.assertEqual(original.severity, "undetermined")

    def test_unknown_source_ref_is_rejected(self):
        correction = ReviewCorrection(field_or_claim_id="rationale", replacement="修正",
                                      source_refs=[uuid4()], reason="补证")
        with self.assertRaisesRegex(ValueError, "outside target run"):
            corrected_insight_payload(clinical_insight(), [correction], set())

    def test_identity_fields_cannot_be_corrected(self):
        with self.assertRaises(ValidationError):
            ReviewCorrection(field_or_claim_id="case_id", replacement=str(uuid4()), reason="禁止")

    def test_approve_cannot_carry_corrections_is_repository_rule(self):
        # Pure service also rejects empty correction lists for the correct path.
        with self.assertRaisesRegex(ValueError, "requires corrections"):
            corrected_insight_payload(clinical_insight(), [], set())


if __name__ == "__main__":
    unittest.main()
