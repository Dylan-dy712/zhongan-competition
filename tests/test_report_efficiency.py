import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.api.app.analysis_sources import compact_schema
from services.api.app.analysis_review import AnalysisReview, review_analysis
from services.api.app.conversation_agent import CareTools, run_agent
from services.api.app.report_llm import draft_report
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.llm_extractor import OpenAiCompatibleExtractor


class ReviewingModel:
    supports_inline_citations = True
    def __init__(self, reply):
        self.reply = reply
        self.complete = MagicMock(return_value={'content':json.dumps(reply)})
        self.reviews = []
    def review_analysis(self, packed, text, citations=None):
        self.reviews.append((packed,text,citations))
        return AnalysisReview(accepted=True,issues=[])


class ReportEfficiencyTests(unittest.TestCase):
    def fixture(self):
        ref = str(uuid4())
        reply = {'text':'票据总额120元。','evidence_refs':[ref],'history_refs':[],
                 'knowledge_refs':[],'citations':[{'quote':'票据总额120元。','source_refs':[ref]}]}
        tools = MagicMock()
        tools.execute.return_value = {'status':'available','next_offset':None,
            'evidence':[{'evidence_id':ref,'text':'票据总额120元。'}]}
        return ref,reply,tools,ReviewingModel(reply)

    def test_shared_draft_skips_generation_but_still_reviews_actual_sources(self):
        ref,draft,tools,model = self.fixture()
        reply,_ = run_agent([], '解释', [], tools,model=model,analysis_mode=True,initial_analysis=draft)
        model.complete.assert_not_called()
        self.assertEqual(len(model.reviews),1)
        self.assertEqual(reply['evidence_refs'],[ref])
        self.assertTrue(reply['performance']['draft_reused'])
        self.assertEqual(model.reviews[0][0][0]['spans'][0][1],'票据总额120元。')

    def test_invalid_stale_unsafe_and_uncited_drafts_fall_back(self):
        for change in [{'evidence_refs':[str(uuid4())]}, {'text':'请自行停药'}, {'citations':[]}]:
            with self.subTest(change=change):
                _,draft,tools,model = self.fixture()
                reply,_ = run_agent([], '解释', [], tools,model=model,analysis_mode=True,
                                    initial_analysis={**draft,**change})
                model.complete.assert_called_once()
                self.assertFalse(reply['performance']['draft_reused'])
                self.assertEqual(len(model.reviews),1)

    def test_rejected_shared_draft_is_corrected_and_reviewed(self):
        _,draft,tools,model = self.fixture()
        original=model.review_analysis
        count=[0]
        def review(*args,**kwargs):
            count[0]+=1
            if count[0]==1:
                return AnalysisReview(accepted=False,issues=[{'category':'payment',
                    'explanation':'核对金额','draft_quote':draft['text'],'source_quote':'票据总额120元。'}])
            return original(*args,**kwargs)
        model.review_analysis=review
        reply,_=run_agent([], '解释', [], tools,model=model,analysis_mode=True,initial_analysis=draft)
        model.complete.assert_called_once()
        self.assertEqual(count[0],2)
        self.assertFalse(reply['performance']['draft_reused'])

    def test_partial_or_low_confidence_sources_do_not_reuse_draft(self):
        for extra in [{'next_offset':200},{'quality_warnings':[{'name':'模糊照片'}]}]:
            _,draft,tools,model=self.fixture()
            tools.execute.return_value.update(extra)
            run_agent([], '解释', [], tools,model=model,analysis_mode=True,initial_analysis=draft)
            model.complete.assert_called_once()

    def test_schema_keeps_constraints_and_property_names(self):
        schema={'title':'Display','properties':{'title':{'type':'string','title':'Title','minLength':2},
                'default':{'type':'integer','default':1}},'required':['title'],
                'additionalProperties':False,'enum':['one','two']}
        result=compact_schema(schema)
        self.assertEqual(result['properties']['title'],{'type':'string','minLength':2})
        self.assertIn('default',result['properties'])
        self.assertFalse(result['additionalProperties'])
        self.assertEqual(result['required'],['title'])

    def test_single_report_call_receives_sources_without_duplicate_material(self):
        valid=json.dumps({'sections':[{'section_type':s,'claims':[]} for s in SECTION_TYPES],'actions':[]})
        with patch.dict('os.environ',{'LLM_BASE_URL':'https://example.invalid','LLM_API_KEY':'synthetic','LLM_MODEL_ID':'synthetic'}), \
             patch.object(OpenAiCompatibleExtractor,'_call',return_value=({'usage':{}},valid)) as call:
            draft_report('原文',[],None,analysis_sources=[{'document':'D1','page':0,'spans':[['S1','原文']]}])
        call.assert_called_once()
        body=json.loads(call.call_args.args[0][1]['content'])
        self.assertNotIn('material',body)
        self.assertEqual(body['authorized_material_pages'][0]['spans'][0][1],'原文')

    def test_review_does_not_repeat_cited_source_text(self):
        text='不能排除感染'
        config=MagicMock();config._call.return_value=({},'{"accepted":true,"issues":[]}')
        packed=[{'document':'D1','page':0,'spans':[['S1',text]]}]
        review_analysis(config,packed,'请核对这个判断',citations=[{'quote':'请核对这个判断','source_refs':['S1']}])
        body=json.loads(config._call.call_args.args[0][1]['content'])
        self.assertEqual(body['original_material_pages'],[{'document':'D1','page':0,'text':'[来源:S1]'+text}])
        self.assertEqual(body['citation_links'][0]['source_refs'],['S1'])
        self.assertEqual(config._call.call_args.args[0][1]['content'].count(text),1)

    def test_outdated_material_report_never_returns_cached_draft(self):
        tools=CareTools(MagicMock(),uuid4(),uuid4())
        with patch('services.api.app.material_report.get_material_report',return_value={'status':'outdated'}):
            self.assertIsNone(tools.reusable_analysis())
        tools.conn.execute.assert_not_called()
