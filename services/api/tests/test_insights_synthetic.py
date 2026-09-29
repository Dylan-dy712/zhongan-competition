"""痛点识别合成测试（unittest）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import CaseFacts, DiagnosisItem, ExpenseItem, ExpenseScope, FieldValue
from app.pipelines.insights import detect_insights


def _fv(v):
    return FieldValue.observed(v, str(v), ["ev-1"], 0.9, "rule@t")


def _facts_with_expenses(totals):
    facts = CaseFacts(case_id="SYN", run_id="r")
    facts.expenses = [
        ExpenseItem(encounter_id="e1", scope=ExpenseScope.total, amount_minor=_fv(t), document_id=f"doc{i}")
        for i, t in enumerate(totals)
    ]
    return facts


class TestCostInsights(unittest.TestCase):
    def test_reconciliation_triggers_on_mismatch(self):
        out = detect_insights(_facts_with_expenses([1234567, 1240000]))
        rec = [i for i in out if i.label_code == "COST_AMOUNT_RECONCILIATION"]
        self.assertTrue(rec)
        self.assertEqual(rec[0].judgment_status.value, "candidate")
        self.assertEqual(rec[0].severity.value, "medium")

    def test_no_reconciliation_on_consistent_totals(self):
        out = detect_insights(_facts_with_expenses([1234567, 1234567]))
        self.assertFalse([i for i in out if i.label_code == "COST_AMOUNT_RECONCILIATION"])


class TestExperienceInsights(unittest.TestCase):
    def test_terminology_barrier(self):
        facts = CaseFacts(case_id="SYN", run_id="r")
        facts.diagnoses = [DiagnosisItem(encounter_id="e1", role="discharge", name=_fv("腰椎间盘突出伴神经根受压"))]
        out = detect_insights(facts)
        term = [i for i in out if i.label_code == "EXP_TERMINOLOGY_BARRIER"]
        self.assertTrue(term)
        self.assertEqual(term[0].judgment_status.value, "supported")

    def test_guidance_gap_requires_discharge(self):
        facts = CaseFacts(case_id="SYN", run_id="r")
        out = detect_insights(facts, {"pages": []})
        self.assertFalse([i for i in out if i.label_code == "EXP_DISCHARGE_GUIDANCE_GAP"])


if __name__ == "__main__":
    unittest.main()
