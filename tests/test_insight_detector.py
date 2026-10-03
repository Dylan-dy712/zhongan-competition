import unittest
from uuid import uuid4

from services.api.app.contracts.core import Insight
from services.api.app.contracts.knowledge import DiseaseCode
from services.api.app.insight_detector import deterministic_candidates, infer_disease_code, merge_semantic_candidates
from services.api.app.knowledge_assembler import KnowledgeAssembler


class InsightDetectorTests(unittest.TestCase):
    def test_cost_mismatch_is_indeterminate_and_evidence_bound(self):
        a, b, doc = uuid4(), uuid4(), uuid4()
        rows = [{"evidence_id": a, "text": "医疗总费用：1000元"},
                {"evidence_id": b, "text": "明细合计：900元"}]
        for row in rows: row.update(document_id=doc,document_version=1,page_index=0)
        item = deterministic_candidates(rows)[0]
        self.assertEqual(item["label"], "COST_AMOUNT_RECONCILIATION")
        self.assertEqual(item["judgment_status"], "indeterminate")
        self.assertEqual(set(item["evidence_ids"]), {str(a), str(b)})

    def test_no_self_pay_deviation_without_comparable_baseline(self):
        self.assertEqual(deterministic_candidates(
            [{"evidence_id": uuid4(), "text": "自付比例：80%"}]), [])

    def test_semantic_candidate_requires_exact_quote(self):
        semantic = [{"label": "CLIN_MEDICATION_CONTEXT_REVIEW", "evidence_quote": "不存在",
                     "rationale": "待核实", "suggested_action": "医学审核",
                     "knowledge_refs": [], "confidence": .8}]
        self.assertEqual(merge_semantic_candidates([], semantic,
            [{"evidence_id": uuid4(), "text": "用药：阿司匹林"}], set()), [])

    def test_clinical_candidate_contract_forces_review(self):
        evidence_id = uuid4()
        semantic = [{"label": "CLIN_MEDICATION_CONTEXT_REVIEW", "evidence_quote": "用药：阿司匹林",
                     "rationale": "存在待核实线索", "suggested_action": "结合诊断复核",
                     "knowledge_refs": [], "confidence": .6}]
        item = merge_semantic_candidates([], semantic,
            [{"evidence_id": evidence_id, "text": "用药：阿司匹林"}], set())[0]
        validated = Insight(case_id=uuid4(), run_id=uuid4(), **item)
        self.assertTrue(validated.review_required)
        self.assertEqual(validated.review_status, "pending")

    def test_terminology_candidate_carries_knowledge_ref(self):
        entries = KnowledgeAssembler().entries_for(DiseaseCode.gx)
        target = next(e for e in entries if e.slot in {"S2", "S11"} and e.title)
        found = deterministic_candidates(
            [{"evidence_id": uuid4(), "text": f"检查提示：{target.title}"}], entries)
        self.assertTrue(any(target.entry_id in x["knowledge_refs"] for x in found))

    def test_disease_inference_is_explicit(self):
        self.assertEqual(infer_disease_code("出院诊断：2型糖尿病"), DiseaseCode.tn)
        self.assertIsNone(infer_disease_code("诊断待明确"))


if __name__ == "__main__":
    unittest.main()
