"""契约层测试（unittest，无第三方测试依赖）：验证规格 §5 的强制行为。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import CaseFacts, Evidence, FieldStatus, FieldValue


class TestFieldValue(unittest.TestCase):
    def test_score_requires_method(self):
        with self.assertRaises(Exception):
            FieldValue(confidence_score=0.9)
        fv = FieldValue(confidence_score=0.9, confidence_method="rule@0.1")
        self.assertEqual(fv.confidence_method, "rule@0.1")

    def test_missing_field_semantics(self):
        fv = FieldValue.missing("not_recorded")
        self.assertIs(fv.status, FieldStatus.missing)
        self.assertIsNone(fv.value)
        self.assertEqual(fv.missing_reason, "not_recorded")


class TestCaseFacts(unittest.TestCase):
    def test_roundtrip(self):
        ev = Evidence(case_id="c1", document_id="d1", page_index=0, line_index=3)
        facts = CaseFacts(case_id="c1", run_id="r1", evidences=[ev])
        d = facts.model_dump(mode="json")
        self.assertEqual(d["evidences"][0]["evidence_id"], ev.evidence_id)
        facts2 = CaseFacts.model_validate(d)
        self.assertIsNone(facts2.evidences[0].bbox)


if __name__ == "__main__":
    unittest.main()
