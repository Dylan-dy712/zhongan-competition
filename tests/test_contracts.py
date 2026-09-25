import unittest
from uuid import uuid4

from pydantic import ValidationError

from services.api.app.contracts.core import Assertion, Evidence, FieldCandidate, FieldStatus, FieldValue, MedicalEvent, TextSpan


class ContractTests(unittest.TestCase):
    def test_observed_requires_evidence(self):
        with self.assertRaises(ValidationError):
            FieldValue[str](field_id=uuid4(), value="肺炎", raw_value="肺炎", status=FieldStatus.observed, evidence_ids=[])

    def test_conflict_keeps_two_sources_without_resolved_value(self):
        a, b = uuid4(), uuid4()
        value = FieldValue[str](field_id=uuid4(), value=None, raw_value=None, status=FieldStatus.conflict,
                                evidence_ids=[a, b], alternatives=[FieldCandidate(value="2026-01-01", evidence_ids=[a]), FieldCandidate(value="2026-01-02", evidence_ids=[b])])
        self.assertIsNone(value.value)
        self.assertEqual(len(value.alternatives), 2)

    def test_suspected_stays_suspected(self):
        event = MedicalEvent(event_id=uuid4(), case_id=uuid4(), encounter_id=uuid4(), event_type="diagnosis",
                             assertion=Assertion.suspected, occurred_at=None, time_precision="unknown", attributes={}, evidence_ids=[uuid4()])
        self.assertEqual(event.assertion, Assertion.suspected)

    def test_invalid_evidence_coordinates_rejected(self):
        with self.assertRaises(ValidationError):
            Evidence(evidence_id=uuid4(), case_id=uuid4(), document_id=uuid4(), document_version=1, page_index=0,
                     text_span=TextSpan(start=0, end=2, text="诊断"), bbox=(0.8, 0.1, 0.2, 0.3),
                     extraction_method="synthetic_fixture", source_hash="a" * 64, parser_version="fixture-1")


if __name__ == "__main__":
    unittest.main()
