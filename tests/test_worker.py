import unittest
import os
import threading
from unittest.mock import MagicMock, patch

from services.api.app.worker import analyze_models, assign_encounter_keys, looks_like_title, text_chunks
from services.api.app.tencent_ocr import normalize_bbox


class Point:
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class Detection:
    Polygon = [Point(10, 20), Point(90, 20), Point(90, 60), Point(10, 60)]


class WorkerTests(unittest.TestCase):
    def test_models_overlap_but_report_receives_grounded_insights_and_fields(self):
        insight_started,insight_finished=threading.Event(),threading.Event()
        caller=threading.get_ident()
        extractor=MagicMock(provider='synthetic',model_id='synthetic')
        def fields(_):
            self.assertTrue(insight_started.wait(2),'Insight must start before extraction returns')
            return {'status':'completed','candidates':{'candidates':[]},'personnel':[]}
        def insights(*_):
            insight_started.set()
            insight_finished.set()
            return {'status':'completed','candidates':[{'label':'EXP_TERMINOLOGY_BARRIER',
                'evidence_quote':'合成材料','rationale':'术语需要解释','suggested_action':'解释术语含义',
                'knowledge_refs':[]}]}
        def report(*args,**kwargs):
            self.assertEqual(threading.get_ident(),caller)
            self.assertEqual(kwargs['personnel'],[])
            self.assertTrue(insight_finished.is_set())
            self.assertEqual(kwargs['care_priorities'][0]['label'],'EXP_TERMINOLOGY_BARRIER')
            return {'status':'completed','draft':{'sections':[],'actions':[]}}
        def advance(stage):
            self.assertEqual(threading.get_ident(),caller,'SQL progress must stay on caller thread')
        extractor.extract.side_effect=fields
        with patch.dict(os.environ,{'LLM_API_KEY':'synthetic-no-network'}), \
             patch('services.api.app.worker.OpenAiCompatibleExtractor',return_value=extractor), \
             patch('services.api.app.worker.detect_semantic',side_effect=insights), \
             patch('services.api.app.worker.draft_report',side_effect=report):
            result=analyze_models('合成材料',[],{}, {},[],{},advance)
        self.assertEqual([r['status'] for r in result[:3]],['completed']*3)
        self.assertEqual(result[-1]['model_schedule'],'parallel')

    def test_excluded_knowledge_does_not_start_insight_or_report_models(self):
        extractor=MagicMock(provider='synthetic',model_id='synthetic')
        extractor.extract.return_value={'status':'completed','candidates':{'candidates':[]}}
        with patch.dict(os.environ,{'LLM_API_KEY':'synthetic-no-network'}), \
             patch('services.api.app.worker.OpenAiCompatibleExtractor',return_value=extractor), \
             patch('services.api.app.worker.detect_semantic') as insights, \
             patch('services.api.app.worker.draft_report') as report:
            result=analyze_models('合成材料',[],None,{},[],{},lambda stage:None,True)
        insights.assert_not_called();report.assert_not_called()
        self.assertEqual(result[1]['status'],'not_configured')

    def test_chunks_use_python_unicode_code_point_offsets(self):
        text = "肺炎🙂复诊"
        chunks = list(text_chunks(text, limit=3))
        self.assertEqual(chunks, [(0, 3, "肺炎🙂"), (3, 5, "复诊")])
        for start, end, value in chunks:
            self.assertEqual(text[start:end], value)

    def test_whitespace_only_chunks_do_not_become_evidence(self):
        self.assertEqual(list(text_chunks("   ", limit=2)), [])

    def test_numbered_heading_is_structural_title(self):
        self.assertTrue(looks_like_title("1. 住院经过"))
        self.assertFalse(looks_like_title("患者今日情况稳定。"))

    def test_ocr_bbox_is_normalized_to_original_image(self):
        self.assertEqual(normalize_bbox(Detection(), 100, 100), [0.1, 0.2, 0.9, 0.6])

    def test_undated_pages_stay_unattributed_and_visits_stay_separate(self):
        parsed = [
            ({"document_id": "D1", "document_version": 1, "document_type": None},
             [{"page_index": 0, "text": "电子病历\n就诊日期：2025-07-19\n诊断：子宫平滑肌瘤"},
              {"page_index": 1, "text": "检查报告，未见日期"}]),
            ({"document_id": "D2", "document_version": 1, "document_type": None},
             [{"page_index": 0, "text": "出院记录\n入院时间：2025-07-28 09:00\n出院时间：2025-08-11 09:20"}]),
        ]
        keys = assign_encounter_keys(parsed)
        self.assertEqual(keys[("D1", 1, 0)], "encounter:outpatient:2025-07-19")
        self.assertEqual(keys[("D1", 1, 1)], "encounter:unattributed")
        self.assertEqual(keys[("D2", 1, 0)], "encounter:inpatient:2025-07-28")

    def test_discharge_only_page_joins_a_nearby_admission_not_a_distant_one(self):
        parsed = [
            ({"document_id": "A", "document_version": 1}, [{"page_index": 0, "text": "入院时间：2025-07-28"}]),
            ({"document_id": "B", "document_version": 1}, [{"page_index": 0, "text": "出院时间：2025-08-11"}]),
            ({"document_id": "C", "document_version": 1}, [{"page_index": 0, "text": "出院时间：2024-01-05"}]),
        ]
        keys = assign_encounter_keys(parsed)
        self.assertEqual(keys[("B", 1, 0)], "encounter:inpatient:2025-07-28")
        self.assertEqual(keys[("C", 1, 0)], "encounter:unattributed")

    def test_discharge_between_two_admissions_binds_to_the_latest_one(self):
        # Two admissions inside the 90-day window: the discharge page joins the latest
        # admission that started on or before it.
        parsed = [
            ({"document_id": "A", "document_version": 1}, [{"page_index": 0, "text": "入院时间：2025-07-28"}]),
            ({"document_id": "B", "document_version": 1}, [{"page_index": 0, "text": "入院时间：2025-08-20"}]),
            ({"document_id": "C", "document_version": 1}, [{"page_index": 0, "text": "出院时间：2025-08-25"}]),
        ]
        keys = assign_encounter_keys(parsed)
        self.assertEqual(keys[("C", 1, 0)], "encounter:inpatient:2025-08-20")

    def test_discharge_of_an_earlier_stay_ignores_a_later_admission(self):
        # A discharge dated before a later admission can only belong to the earlier
        # stay, even though both sit inside the match window.
        parsed = [
            ({"document_id": "A", "document_version": 1}, [{"page_index": 0, "text": "入院时间：2025-07-28"}]),
            ({"document_id": "B", "document_version": 1}, [{"page_index": 0, "text": "入院时间：2025-08-20"}]),
            ({"document_id": "C", "document_version": 1}, [{"page_index": 0, "text": "出院时间：2025-08-11"}]),
        ]
        keys = assign_encounter_keys(parsed)
        self.assertEqual(keys[("C", 1, 0)], "encounter:inpatient:2025-07-28")


if __name__ == "__main__":
    unittest.main()
