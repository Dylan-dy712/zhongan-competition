import copy,json,os,tempfile,unittest
from unittest.mock import patch
from uuid import uuid4
from services.api.app.judge_narrative_cache import generic_context,write_prepared,read_prepared,artifact_path

class PreparedNarrativeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'ZHONGAN_JUDGE_RECOGNITION_ROOT':tmp.name});env.start();self.addCleanup(env.stop)
        self.ref=str(uuid4());self.row={'evidence_id':self.ref,'source_hash':'a'*64,'page_index':0,'text_value':'合成材料原文。','parser_version':'synthetic'}
        self.checked={'sample_id':'synthetic','version':'v1','rows':[self.row]}
        self.scope=patch('services.api.app.judge_narrative_cache.scope',return_value=self.checked);self.scope.start();self.addCleanup(self.scope.stop)
        self.identity=patch('services.api.app.judge_narrative_cache.identity',return_value='b'*64);self.identity.start();self.addCleanup(self.identity.stop)
        body='合成材料中的安排仍保留待核对限定，向诊疗团队确认已有记录，准备好原有材料。'*20
        self.reply={'text':body,'evidence_refs':[self.ref],'knowledge_refs':[],'history_refs':[],
            'citations':[{'quote':body,'source_refs':[self.ref]}],
            'performance':{'source_read_complete':True,'review_calls':1,'partial_delivery':False},'guidance_delivery':{'status':'passed'}}

    def test_draft_has_no_case_evidence_ids_and_rebinds_to_new_case(self):
        key=write_prepared(None,None,None,None,self.reply,{})
        self.assertNotIn(self.ref,artifact_path(key).read_text(encoding='utf-8'))
        fresh=str(uuid4());self.row['evidence_id']=fresh
        result=read_prepared(None,None,None,None)
        self.assertEqual(result['draft']['text'],self.reply['text'])
        self.assertEqual(result['draft']['evidence_refs'],[fresh])
        self.assertEqual(result['draft']['citations'][0]['source_refs'],[fresh])

    def test_partial_unreviewed_or_failed_reading_drafts_are_not_prepared(self):
        for change in ('partial','no_review','reading'):
            reply=copy.deepcopy(self.reply)
            if change=='partial':reply['performance']['partial_delivery']=True
            if change=='no_review':reply['performance']['review_calls']=0
            if change=='reading':reply['guidance_delivery']['status']='needs_improvement'
            with self.assertRaises(ValueError):write_prepared(None,None,None,None,reply,{})

    def test_corrupt_or_ineligible_scope_never_seeds_a_draft(self):
        key=write_prepared(None,None,None,None,self.reply,{})
        payload=json.loads(artifact_path(key).read_text(encoding='utf-8'));payload['data']['draft']['text']='changed'
        artifact_path(key).write_text(json.dumps(payload))
        self.assertIsNone(read_prepared(None,None,None,None))
        with patch('services.api.app.judge_narrative_cache.scope',return_value=None):
            self.assertIsNone(read_prepared(None,None,None,None))

    def test_personal_context_questions_memory_and_updates_do_not_match(self):
        context={'judge_demo':True,'sample_id':'synthetic','sample_version':'v1','notice':'合成材料'}
        question='请分析本次上传材料，整理就医经过、费用与待补充信息。'
        self.assertTrue(generic_context(context,[question],False,None,[]))
        self.assertTrue(generic_context(context,[question],True,None,[]))
        self.assertFalse(generic_context({**context,'concern':'个人问题'},[question],False,None,[]))
        self.assertFalse(generic_context(context,['我现在很疼'],False,None,[]))
        self.assertTrue(generic_context(context,[question,question],False,None,[]))
        self.assertFalse(generic_context(context,[question,'个人补充'],False,None,[]))
        self.assertFalse(generic_context(context,[question]*21,False,None,[]))
        self.assertFalse(generic_context(context,[question],False,{'items':['memory']},[]))
        self.assertFalse(generic_context(context,[question],False,None,[{'statement':'个人补充'}]))

    def test_reused_draft_still_requires_independent_review_for_new_submission(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from services.api.app.conversation_agent import CareTools,run_agent
        from services.api.app.analysis_review import AnalysisReview,ReviewIssue
        class Reviewer:
            supports_inline_citations=True
            config=SimpleNamespace(base_url='https://qianfan.baidubce.com/v2')
            accepted=True
            reviews=0
            def complete(self,*args,**kwargs):raise AssertionError('No new prose for accepted prepared draft')
            def review_analysis(self,*args,**kwargs):
                self.reviews+=1
                return AnalysisReview(accepted=self.accepted,issues=[] if self.accepted else [ReviewIssue(
                    category='phase',explanation='合成复核拒绝',source_quote='合成原文',draft_quote='合成正文')])
        write_prepared(None,None,None,None,self.reply,{})
        prepared=read_prepared(None,None,None,None)['draft']
        tools=CareTools(MagicMock(),uuid4(),uuid4());tools.prepared_sample_draft=True;tools.deferred_patient_analysis=True
        tools.draft_guidance_delivery={'status':'passed'}
        tools.execute=MagicMock(side_effect=lambda name,args: {'status':'available','results':[]} if name=='search_knowledge' else {
            'status':'available','next_offset':None,'evidence':[{'evidence_id':self.ref,'text':'合成材料原文。'}]})
        tools.validate_reply=MagicMock();tools.guidance_context=MagicMock(return_value={})
        tools.reject_shared_analysis=MagicMock();tools.resolve_draft_knowledge=MagicMock(return_value=[])
        model=Reviewer()
        reply,_=run_agent([],'完整解读',[],tools,model=model,analysis_mode=True,initial_analysis=prepared)
        self.assertTrue(reply['sample_preload']);self.assertTrue(reply['performance']['draft_reused'])
        self.assertEqual(model.reviews,1)
        model.accepted=False
        with self.assertRaisesRegex(AssertionError,'No new prose'):
            run_agent([],'完整解读',[],tools,model=model,analysis_mode=True,initial_analysis=prepared)
