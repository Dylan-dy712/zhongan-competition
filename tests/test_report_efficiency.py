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

    def test_partial_sources_do_not_reuse_draft(self):
        for extra in [{'next_offset':200,'evidence':[{'evidence_id':str(uuid4()),'text':'长'*28001}]}]:
            _,draft,tools,model=self.fixture()
            if 'evidence' in extra:
                extra={**extra,'evidence':tools.execute.return_value['evidence']+extra['evidence']}
            tools.execute.return_value.update(extra)
            run_agent([], '解释', [], tools,model=model,analysis_mode=True,initial_analysis=draft)
            model.complete.assert_called_once()

    def test_replacement_after_rejected_draft_can_repair_its_format(self):
        _,draft,tools,model=self.fixture()
        missing_citations={**draft,'citations':[]}
        model.complete.side_effect=[{'content':json.dumps(missing_citations)},
                                    {'content':json.dumps(draft)}]
        model.review_analysis=MagicMock(side_effect=[
            AnalysisReview(accepted=False,issues=[{'category':'payment','explanation':'需核对原文金额',
                'draft_quote':draft['text'],'source_quote':'票据总额120元。'}]),
            AnalysisReview(accepted=True,issues=[])])
        result,_=run_agent([],'解释',[],tools,model=model,analysis_mode=True,initial_analysis=draft)
        self.assertEqual(result['text'],draft['text'])
        self.assertEqual(model.complete.call_count,2)
        self.assertEqual(model.review_analysis.call_count,2)
        self.assertFalse(result['performance']['draft_reused'])
        self.assertIn('格式错误项',model.complete.call_args.args[0][-1]['content'])

    def test_replacement_with_repeated_format_errors_is_not_delivered(self):
        _,draft,tools,model=self.fixture()
        model.complete.return_value={'content':json.dumps({**draft,'citations':[]})}
        model.review_analysis=MagicMock(return_value=AnalysisReview(accepted=False,issues=[
            {'category':'payment','explanation':'需核对原文金额','draft_quote':draft['text'],
             'source_quote':'票据总额120元。'}]))
        with self.assertRaisesRegex(ValueError,'INLINE_CITATIONS_REQUIRED'):
            run_agent([],'解释',[],tools,model=model,analysis_mode=True,initial_analysis=draft)
        self.assertEqual(model.complete.call_count,2)
        self.assertEqual(model.review_analysis.call_count,1)

    def test_quality_warning_preserves_readable_draft_and_still_reviews_with_notice(self):
        _,draft,tools,model=self.fixture()
        tools.execute.return_value['quality_warnings']=[{'name':'模糊照片'}]
        reply,_=run_agent([], '解释', [],tools,model=model,analysis_mode=True,initial_analysis=draft)
        model.complete.assert_not_called()
        self.assertTrue(reply['performance']['draft_reused'])
        self.assertIn('部分材料文字识别不够清晰',reply['text'])
        self.assertEqual(len(model.reviews),1)
        self.assertEqual(model.reviews[0][1],reply['text'])

    def test_quality_warning_does_not_authorize_a_missing_draft_source(self):
        _,draft,tools,model=self.fixture()
        tools.execute.return_value['quality_warnings']=[{'name':'模糊照片'}]
        stale={**draft,'evidence_refs':[str(uuid4())]}
        reply,_=run_agent([], '解释', [],tools,model=model,analysis_mode=True,initial_analysis=stale)
        model.complete.assert_called_once()
        self.assertFalse(reply['performance']['draft_reused'])

    def test_quality_warning_never_bypasses_rejection_by_independent_review(self):
        _,draft,tools,model=self.fixture()
        tools.execute.return_value['quality_warnings']=[{'name':'模糊照片'}]
        original=model.review_analysis
        count=[0]
        def review(*args,**kwargs):
            count[0]+=1
            if count[0]==1:
                return AnalysisReview(accepted=False,issues=[{'category':'payment',
                    'explanation':'需核对原文金额','draft_quote':draft['text'],'source_quote':'票据总额120元。'}])
            return original(*args,**kwargs)
        model.review_analysis=review
        reply,_=run_agent([], '解释', [],tools,model=model,analysis_mode=True,initial_analysis=draft)
        self.assertEqual(count[0],2)
        model.complete.assert_called_once()
        self.assertFalse(reply['performance']['draft_reused'])

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

    def test_source_rejected_draft_is_excluded_from_the_next_retry(self):
        _,draft,_,_=self.fixture()
        run_id=str(uuid4())
        conn=MagicMock()
        row={'draft':draft,'usage_metadata':{}}
        conn.execute.return_value.fetchone.side_effect=lambda:row
        tools=CareTools(conn,uuid4(),uuid4())
        with patch('services.api.app.material_report.get_material_report',return_value={'status':'available','run_id':run_id}):
            self.assertEqual(tools.reusable_analysis(),draft)
            tools.reject_shared_analysis()
            update=conn.execute.call_args
            self.assertIn('patient_analysis_rejected',update.args[0])
            self.assertEqual(update.args[1][0],run_id)
            row['usage_metadata']['patient_analysis_rejected']=True
            self.assertIsNone(tools.reusable_analysis())
        self.assertEqual(row['draft'],draft)

    def test_rejected_old_draft_cannot_mark_a_new_analysis(self):
        _,draft,_,_=self.fixture()
        old_run,new_run=str(uuid4()),str(uuid4())
        conn=MagicMock();conn.execute.return_value.fetchone.return_value={'draft':draft,'usage_metadata':{}}
        tools=CareTools(conn,uuid4(),uuid4())
        with patch('services.api.app.material_report.get_material_report',side_effect=[
                {'status':'available','run_id':old_run},{'status':'available','run_id':new_run}]):
            self.assertEqual(tools.reusable_analysis(),draft)
            conn.execute.reset_mock()
            tools.reject_shared_analysis()
            conn.execute.assert_not_called()

    def test_planned_check_correction_requires_independent_second_review(self):
        ref=str(uuid4())
        source='辅助检查：血常规。辅助检查结果：无。'
        bad='12月19日已完成抽血化验。'
        corrected='医生安排了血常规检查，材料未提供检查结果。'
        draft={'text':bad,'evidence_refs':[ref],'history_refs':[],'knowledge_refs':[],
               'citations':[{'quote':bad,'source_refs':[ref]}]}
        reply={**draft,'text':corrected,'citations':[{'quote':corrected,'source_refs':[ref]}]}
        tools=MagicMock(spec=CareTools)
        tools.knowledge_sources={};tools.draft_guidance_delivery=None
        tools.resolve_draft_knowledge.return_value=[]
        tools.guidance_context.return_value={}
        tools.execute.side_effect=lambda name,args:{'status':'available','next_offset':None,
            'evidence':[{'evidence_id':ref,'text':source}],'results':[]}
        model=ReviewingModel(reply)
        model.review_analysis=MagicMock(side_effect=[
            AnalysisReview(accepted=False,issues=[{'category':'phase','explanation':'只有检查安排',
                'draft_quote':bad,'source_quote':source}]),AnalysisReview(accepted=True,issues=[])])
        result,_=run_agent([],'解释',[],tools,model=model,analysis_mode=True,initial_analysis=draft)
        self.assertEqual(result['text'],corrected)
        self.assertEqual(model.review_analysis.call_count,2)
        tools.reject_shared_analysis.assert_called_once()
        messages=model.complete.call_args.args[0]
        self.assertIn('执行状态待核实',messages[-1]['content'])
        self.assertIn(source,json.dumps(messages,ensure_ascii=False))
