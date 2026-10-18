import json,os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4

from services.api.app.report_llm import draft_report,StructuredDraftReport,normalize_report_wire
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.analysis_review import AnalysisReview
from services.api.app.guidance_quality import GuidanceQuality
from services.api.app.conversation_agent import run_agent,CareTools
from services.api.app.worker import analyze_models


class DeferredSampleTests(unittest.TestCase):
    def test_only_empty_redundant_section_actions_are_normalized(self):
        action={'action_text':'核对合成记录','source_quote':'合成记录','owner_role':'patient',
                'due_at':None,'due_source':'unknown','rationale':'核对已有信息'}
        original={'sections':[{'section_type':key,'claims':[],'actions':[]} for key in SECTION_TYPES],
                  'actions':[action],'patient_analysis':None}
        normalized,changes=normalize_report_wire(json.dumps(original),[])
        parsed=StructuredDraftReport.model_validate(normalized)
        self.assertEqual(len(parsed.sections),6)
        self.assertEqual(parsed.actions[0].action_text,action['action_text'])
        self.assertEqual(changes,['empty_section_actions_removed'])
        original['sections'][0]['actions']=[action]
        normalized,_=normalize_report_wire(json.dumps(original),[])
        with self.assertRaises(ValueError):StructuredDraftReport.model_validate(normalized)

    def test_structured_report_keeps_reference_topics_without_seeding_patient_prose(self):
        conn=MagicMock()
        conn.execute.return_value.fetchone.return_value={'draft':None,
            'usage_metadata':{'patient_analysis_mode':'deferred'},
            'structured':{'sections':[{'claims':[{'knowledge_refs':['SYN-DIAGNOSIS','SYN-COST','SYN-DIAGNOSIS']}]}]}}
        tools=CareTools(conn,uuid4(),uuid4())
        with patch('services.api.app.material_report.get_material_report',return_value={'status':'available','run_id':str(uuid4())}), \
             patch.object(CareTools,'track_report_memory'):
            self.assertIsNone(tools.reusable_analysis())
        self.assertEqual(tools.deferred_knowledge_refs,['SYN-DIAGNOSIS','SYN-COST'])
        self.assertTrue(tools.deferred_patient_analysis)

    def test_structured_stage_does_not_generate_or_review_a_discarded_patient_body(self):
        sections=[{'section_type':key,'claims':[]} for key in SECTION_TYPES]
        wire=json.dumps({'sections':sections,'actions':[],'patient_analysis':None})
        with patch.dict(os.environ,{'LLM_BASE_URL':'https://qianfan.baidubce.com/v2','LLM_API_KEY':'synthetic',
                                   'LLM_MODEL_ID':'glm-5.3-flash'}), \
             patch('services.api.app.report_llm.OpenAiCompatibleExtractor._call',return_value=({},wire)) as call, \
             patch('services.api.app.report_llm.review_guidance_quality',side_effect=AssertionError('Review the final body instead')):
            result=draft_report('合成原文',[],None,analysis_sources=[{'document':'D1','page':0,'spans':[['S1','合成原文']]}],
                                defer_patient_analysis=True)
        self.assertEqual(result['status'],'completed')
        self.assertIsNone(result['draft']['patient_analysis'])
        self.assertEqual(len(result['draft']['sections']),6)
        self.assertEqual(result['usage_metadata']['patient_analysis_mode'],'deferred')
        self.assertEqual(call.call_count,1)
        schema=json.loads(call.call_args.args[0][1]['content'])['schema']
        self.assertEqual(schema['properties']['patient_analysis']['type'],'null')
        self.assertNotIn('PatientAnalysis',schema['$defs'])
        messages=call.call_args.args[0]
        self.assertNotIn('同时返回 clarification_questions',messages[0]['content'])
        self.assertNotIn('patient_analysis是完整报告正文',messages[0]['content'])
        self.assertNotIn('min_body_chars',json.loads(messages[1]['content'])['reading_requirements'])
        with self.assertRaises(ValueError):StructuredDraftReport.model_validate({'sections':sections[:5],'actions':[]})

    def test_worker_passes_deferred_mode_without_bypassing_fields_and_insights(self):
        extractor=MagicMock(provider='synthetic',model_id='synthetic')
        extractor.extract.return_value={'status':'completed','candidates':{'candidates':[]},'personnel':[]}
        with patch.dict(os.environ,{'LLM_API_KEY':'synthetic'}), \
             patch('services.api.app.worker.OpenAiCompatibleExtractor',return_value=extractor), \
             patch('services.api.app.worker.detect_semantic',return_value={'status':'completed','candidates':[]}) as insights, \
             patch('services.api.app.worker.draft_report',return_value={'status':'completed',
                 'draft':{'sections':[],'actions':[],'patient_analysis':None}}) as report:
            analyze_models('合成原文',[],None,{},[],{},lambda stage:None,defer_patient_analysis=True)
        self.assertTrue(report.call_args.kwargs['defer_patient_analysis'])
        extractor.extract.assert_called_once();insights.assert_called_once()

    def test_final_body_still_runs_independent_source_and_reading_quality_review(self):
        body=('本次合成材料中的复诊安排仍需核对，带好已有记录向诊疗团队确认。'*30)
        class Script:
            config=SimpleNamespace(base_url='https://qianfan.baidubce.com/v2')
            source_reviews=quality_reviews=0
            def complete(self,*args,**kwargs):
                return {'content':json.dumps({'text':body,'evidence_refs':['S1'],'history_refs':[]})}
            def review_analysis(self,*args,**kwargs):
                self.source_reviews+=1
                return AnalysisReview(accepted=True,issues=[])
            def review_guidance(self,*args,**kwargs):
                self.quality_reviews+=1
                return GuidanceQuality(**{key:True for key in GuidanceQuality.model_fields if key not in {'issues','explanations'}})
        model=Script();tools=MagicMock()
        tools.execute.return_value={'status':'available','next_offset':None,'evidence':[{'evidence_id':str(uuid4()),'text':'合成原文，复诊安排待核对。'}]}
        reply,_=run_agent([],'完整解读',[],tools,model=model,analysis_mode=True,initial_analysis=None)
        self.assertEqual(reply['text'],body)
        self.assertGreaterEqual(len(reply['text']),650)
        self.assertEqual(model.source_reviews,1);self.assertEqual(model.quality_reviews,1)
        self.assertFalse(reply['performance']['draft_reused'])
