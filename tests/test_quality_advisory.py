"""Quality grades cannot discard source-checked patient prose. Invented data only."""
import json
import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock,patch
import requests

from services.api.app.analysis_review import AnalysisReview
from services.api.app.conversation_agent import CareTools,run_agent
from services.api.app.guidance_quality import GuidanceQuality,guidance_delivery


class Model:
    supports_inline_citations=True
    def __init__(self,reply,quality):
        self.config=SimpleNamespace(base_url='https://qianfan.baidubce.com/v2')
        self.complete=MagicMock(return_value={'content':json.dumps(reply)})
        self.fidelity=MagicMock(return_value=AnalysisReview(accepted=True,issues=[]))
        self.quality=MagicMock(side_effect=quality) if isinstance(quality,Exception) else MagicMock(return_value=quality)
    def review_analysis(self,*args,**kwargs):return self.fidelity(*args,**kwargs)
    def review_guidance(self,*args,**kwargs):return self.quality(*args,**kwargs)


class Sources(CareTools):
    def __init__(self,ref,material,delivery=None):
        self.ref=ref;self.material=material;self.knowledge_sources={}
        self.draft_guidance_delivery=delivery
    def execute(self,name,args):
        if name=='read_materials':
            return {'status':'available','next_offset':None,'evidence':[{'evidence_id':self.ref,'text':self.material}]}
        assert name=='search_knowledge'
        return {'status':'not_found','results':[]}
    def resolve_draft_knowledge(self,draft,case_text):return []
    def guidance_context(self,case_text):return {}
    def validate_reply(self,reply):
        assert set(map(str,reply.evidence_refs))=={self.ref}
        assert not reply.knowledge_refs and not reply.history_refs


class QualityAdvisoryTests(unittest.TestCase):
    def fixture(self,**changes):
        ref=str(uuid4())
        draft={'text':'票据总额120元。','evidence_refs':[ref],'history_refs':[],
               'knowledge_refs':[],'citations':[{'quote':'票据总额120元。','source_refs':[ref]}]}
        quality=GuidanceQuality(**{key:True for key in GuidanceQuality.model_fields if key not in {'issues','explanations'}},**changes)
        return draft,Sources(ref,'票据总额120元。'),quality

    def test_failed_quality_is_delivered_after_factual_review_without_a_rewrite(self):
        draft,tools,quality=self.fixture()
        quality=quality.model_copy(update={'explanation_clear':False,'issues':['解释不够清楚']})
        model=Model(draft,quality)
        answer,_=run_agent([],'解释',[],tools,model=model,analysis_mode=True)
        self.assertEqual(answer['text'],draft['text'])
        self.assertEqual(answer['guidance_delivery']['status'],'needs_improvement')
        self.assertEqual(answer['performance']['guidance_quality_assessments'][0]['explanation_clear'],False)
        model.complete.assert_called_once();model.fidelity.assert_called_once();model.quality.assert_called_once()

    def test_quality_timeout_preserves_the_factually_checked_answer(self):
        draft,tools,_=self.fixture()
        model=Model(draft,requests.ReadTimeout('private input or key'))
        answer,_=run_agent([],'解释',[],tools,model=model,analysis_mode=True)
        self.assertEqual(answer['text'],draft['text'])
        self.assertEqual(answer['guidance_delivery']['status'],'unchecked')
        self.assertNotIn('private',json.dumps(answer))
        model.complete.assert_called_once();model.fidelity.assert_called_once()

    def test_brief_shared_draft_is_reused_and_warned_instead_of_discarded(self):
        draft,tools,quality=self.fixture()
        tools.material+='诊断肺炎，治疗手术，出院医嘱复诊，费用票据。'*100
        model=Model(draft,quality)
        answer,_=run_agent([],'解释',[],tools,model=model,analysis_mode=True,initial_analysis=draft)
        self.assertEqual(answer['text'],draft['text'])
        self.assertEqual(answer['guidance_delivery']['status'],'needs_improvement')
        self.assertTrue(answer['performance']['draft_reused'])
        model.complete.assert_not_called();model.quality.assert_not_called();model.fidelity.assert_called_once()

    def test_cached_quality_note_is_carried_to_the_visible_answer_without_new_grade(self):
        draft,tools,quality=self.fixture()
        quality=quality.model_copy(update={'support_personalized':False})
        tools.draft_guidance_delivery=guidance_delivery(quality)
        model=Model(draft,quality)
        answer,_=run_agent([],'解释',[],tools,model=model,analysis_mode=True,initial_analysis=draft)
        self.assertEqual(answer['guidance_delivery'],tools.draft_guidance_delivery)
        model.complete.assert_not_called();model.quality.assert_not_called();model.fidelity.assert_called_once()

    def test_bad_facts_cannot_be_approved_by_advisory_quality(self):
        draft,tools,quality=self.fixture()
        model=Model(draft,quality)
        model.fidelity.return_value=AnalysisReview(accepted=False,issues=[{'category':'payment',
            'explanation':'原文不支持金额','draft_quote':draft['text'],'source_quote':'票据总额120元。'}])
        with patch('services.api.app.conversation_agent.verified_partial',return_value=None),\
             self.assertRaisesRegex(ValueError,'ANALYSIS_FIDELITY_REJECTED'):
            run_agent([],'解释',[],tools,model=model,analysis_mode=True)
        self.assertEqual(model.fidelity.call_count,2)
        model.quality.assert_not_called()

    def test_reusable_draft_loads_quality_only_after_current_material_checks(self):
        draft,_,quality=self.fixture()
        quality=quality.model_copy(update={'costs_understood':False})
        conn=MagicMock();conn.execute.return_value.fetchone.return_value={
            'draft':draft,'usage_metadata':{'guidance_delivery':guidance_delivery(quality)}}
        tools=CareTools(conn,uuid4(),uuid4())
        with patch('services.api.app.material_report.get_material_report',return_value={'status':'available','run_id':str(uuid4())}):
            self.assertEqual(tools.reusable_analysis(),draft)
        self.assertEqual(tools.draft_guidance_delivery['status'],'needs_improvement')
