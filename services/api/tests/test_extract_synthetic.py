"""抽取器合成夹具测试（unittest）：日期世纪推断、住院天数推导、费用口径。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipelines.extract import _infer_century, extract_facts, parse_amount, parse_date


def _page(doc_type, lines, uid="p1"):
    return {
        "page_uid": uid, "document_id": "doc-" + uid, "page_index": 0, "file": f"x/{uid}.jpg",
        "doc_hint": uid, "image_size": {"w": 1000, "h": 1400},
        "lines": [{"text": t, "score": 0.95, "bbox": [0.1, 0.1, 0.9, 0.2]} for t in lines],
        "text": "\n".join(lines), "ocr_status": "ok",
        "classification": {"doc_type": doc_type, "confidence": 0.9},
    }


class TestParsers(unittest.TestCase):
    def test_parse_date_formats(self):
        self.assertEqual(parse_date("2025-10-27")[0], "2025-10-27")
        self.assertEqual(parse_date("2025年10月27日出院")[0], "2025-10-27")
        self.assertEqual(parse_date("2025/10/27")[0], "2025-10-27")
        self.assertIsNone(parse_date("无日期"))

    def test_parse_amount_ocr_noise(self):
        self.assertEqual(parse_amount("1,500.00"), 150000)
        self.assertEqual(parse_amount("175. 00"), 17500)
        self.assertEqual(parse_amount("合计：12，345.67元"), 1234567)
        self.assertIsNone(parse_amount("无金额"))

    def test_infer_century_suffix_matching(self):
        page = {"lines": [{"text": "出院日期2025年10月30日"}]}
        self.assertEqual(_infer_century(page, "5"), "2025")
        self.assertEqual(_infer_century(page, "25"), "2025")


class TestExtractCore(unittest.TestCase):
    def test_core_fields(self):
        pages = [
            _page("discharge_summary", [
                "合成市第一医院", "出院小结",
                "入院日期2025年10月27日", "出院日期2025年10月30日",
                "入院诊断肺部感染", "出院诊断社区获得性肺炎",
                "出院医嘱：2周后复查胸片",
                "出院带药：头孢克肟片 0.1g 每日两次",
            ], "s1"),
            _page("medical_record_front", [
                "住院费用（元）：总费用12,345.67",
                "（自付金额：3,456.78自费金额：1,000.00",
            ], "s2"),
        ]
        facts = extract_facts({"case_id": "SYN-1", "pages": pages, "documents": []})
        enc = facts.encounters[0]
        self.assertEqual(enc.hospital.value, "合成市第一医院")
        self.assertEqual(enc.admission_date.value, "2025-10-27")
        self.assertEqual(enc.discharge_date.value, "2025-10-30")
        self.assertEqual(enc.stay_days.value, 3)
        self.assertEqual(enc.stay_days.status.value, "derived")
        scopes = {e.scope: e.amount_minor.value for e in facts.expenses}
        self.assertEqual(scopes["total"], 1234567)
        self.assertEqual(scopes["self_paid"], 345678)
        self.assertEqual(scopes["out_of_catalog"], 100000)
        dx = [d.name.value for d in facts.diagnoses]
        self.assertIn("社区获得性肺炎", dx)
        meds = [m.name.value for m in facts.medications]
        self.assertTrue(any("头孢克肟" in m for m in meds))
        self.assertTrue(all(d.name.evidence_ids for d in facts.diagnoses))

    def test_stay_days_conflict_on_bad_dates(self):
        pages = [_page("discharge_summary", [
            "入院日期2005年10月27日", "出院日期2025年10月30日",
        ])]
        facts = extract_facts({"case_id": "SYN-2", "pages": pages, "documents": []})
        enc = facts.encounters[0]
        self.assertIsNone(enc.stay_days.value)
        self.assertEqual(enc.stay_days.status.value, "conflict")


if __name__ == "__main__":
    unittest.main()
