"""API 测试（unittest）：合成运行产物 + 临时 work 目录。"""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SECTIONS = ("diagnosis_explanation", "treatment_review", "cost_explanation",
            "recovery_plan", "emotional_support", "next_visit_advice")


def _make_run():
    return {
        "run_id": "r1", "case_id": "SYN1", "input_hash": "h", "schema_version": "0.1.0",
        "execution_mode": "mock", "status": "completed",
        "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:01+00:00",
        "stages": {"guidance": {"mode": "mock"}},
        "facts": {"encounters": [{"hospital": {"value": "合成医院"}, "admission_date": {"value": "2025-10-27"},
                                  "discharge_date": {"value": "2025-10-30"}, "stay_days": {"value": 3}}],
                   "diagnoses": [{"name": {"value": "合成诊断"}}], "procedures": [], "medications": [],
                   "expenses": [], "evidences": []},
        "insights": [{"insight_id": "i1", "label_code": "EXP_TERMINOLOGY_BARRIER", "severity": "low",
                      "category": "experience", "rationale": "r", "judgment_status": "supported"}],
        "report": {"report_version": 1, "sections": [{"key": k, "title_zh": k, "content": "c"} for k in SECTIONS],
                   "actions": [], "claims": []},
        "recommendations": [],
        "llm_usage": {"calls": 0},
    }


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        runs = Path(cls.tmp.name) / "runs"
        runs.mkdir()
        (runs / "SYN1.json").write_text(json.dumps(_make_run(), ensure_ascii=False), encoding="utf-8")
        import os

        os.environ["ZANH_WORK_DIR"] = cls.tmp.name
        import app.config as cfg

        importlib.reload(cfg)
        cls._old_get_settings = cfg.get_settings
        cfg.get_settings = lambda: cfg.Settings()
        import app.main as main_mod

        importlib.reload(main_mod)
        from fastapi.testclient import TestClient

        cls.client = TestClient(main_mod.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_list_and_detail(self):
        r = self.client.get("/v1/cases")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)
        cid = r.json()["items"][0]["case_id"]
        self.assertEqual(self.client.get(f"/v1/cases/{cid}").status_code, 200)
        facts = self.client.get(f"/v1/cases/{cid}/facts").json()
        self.assertEqual(facts["diagnoses"][0]["name"]["value"], "合成诊断")
        rep = self.client.get(f"/v1/cases/{cid}/reports/1").json()
        self.assertEqual(len(rep["sections"]), 6)

    def test_not_found_and_invalid(self):
        self.assertEqual(self.client.get("/v1/cases/NOPE").status_code, 404)
        # 路径穿越形态被路由拒绝（404）或参数校验拒绝（422）均可，不允许 200
        self.assertIn(self.client.get("/v1/cases/..%2Fetc").status_code, (404, 422))

    def test_feedback(self):
        r = self.client.post("/v1/feedback", json={"case_id": "SYN1", "type": "verify_fact", "text": "x"})
        self.assertEqual(r.status_code, 200)
        bad = self.client.post("/v1/feedback", json={"case_id": "SYN1", "type": "weird"})
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
