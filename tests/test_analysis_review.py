import json
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4
from services.api.app.analysis_review import AnalysisReview,review_analysis
from services.api.app.conversation_agent import AgentModel,run_agent

class ReviewTests(unittest.TestCase):
    def test_verdict_is_strict_and_consistent(self):
        for value in [{'accepted':'true','issues':[]},{'accepted':True,'issues':[{'category':'qualifier','explanation':'限定遗漏'}]},
                      {'accepted':False,'issues':[]},{'accepted':True,'issues':[],'extra':1}]:
            with self.assertRaises(ValueError):AnalysisReview.model_validate(value)

    def test_review_receives_exact_originals_and_separate_draft(self):
        config=MagicMock();config._call.return_value=({'usage':{'total_tokens':12}},'{"accepted":true,"issues":[]}')
        source=[{'document':'D1','page':0,'spans':[['S1','未见肺炎；不能排除感染']]}]
        verdict,usage=review_analysis(config,source,'1. **未见肺炎**')
        self.assertTrue(verdict.accepted)
        messages=config._call.call_args.args[0]
        self.assertEqual(json.loads(messages[1]['content'])['original_material_pages'],[{'document':'D1','page':0,'text':'未见肺炎；不能排除感染'}])
        self.assertIn('住院用药',messages[0]['content'])
        self.assertEqual(config._call.call_args.kwargs['workload'],'fidelity')

    def test_ungrounded_review_cannot_modify_or_approve_draft(self):
        config=MagicMock();config._call.return_value=({},json.dumps({'accepted':False,'issues':[{
            'category':'qualifier','explanation':'不符','source_quote':'不存在的来源','draft_quote':'当前肺炎'}]}))
        verdict,_=review_analysis(config,[{'document':'D1','page':0,'spans':[['S1','既往肺炎']]}],'当前肺炎')
        self.assertFalse(verdict.accepted)
        self.assertTrue(verdict.unverified)
        self.assertEqual(verdict.issues[0].source_quote,'')
        self.assertNotIn('不存在的来源',verdict.issues[0].explanation)

    def test_unlocatable_draft_cannot_be_used_to_remove_a_point(self):
        config=MagicMock();config._call.return_value=({},json.dumps({'accepted':False,'issues':[{
            'category':'scope','explanation':'不符','source_quote':'既往肺炎','draft_quote':'不存在的草稿句'}]}))
        with self.assertRaisesRegex(ValueError,'UNGROUNDED_ANALYSIS_REVIEW'):
            review_analysis(config,[{'document':'D1','page':0,'spans':[['S1','既往肺炎']]}],'当前肺炎')

    def test_grounded_issue_is_confirmed_with_focused_reasoning(self):
        for confirmed in [True,False]:
            config=MagicMock();config._call.side_effect=[({},json.dumps({'accepted':False,'issues':[{
                'category':'qualifier','explanation':'既往不能变当前','source_quote':'既往肺炎','draft_quote':'当前肺炎'}]})),
                ({},json.dumps({'confirmed_1':confirmed,'confirmed_2':False,'confirmed_3':False}))]
            verdict,usage=review_analysis(config,[{'document':'D1','page':0,'spans':[['S1','既往肺炎']]}],'当前肺炎')
            self.assertEqual(verdict.accepted,not confirmed)
            self.assertEqual(config._call.call_args.kwargs['workload'],'review')
            self.assertEqual(len(usage['request_usages']),2)

    def test_unused_judgment_fields_optional_but_existing_issues_required(self):
        issue={'category':'qualifier','explanation':'既往不是当前','source_quote':'既往肺炎','draft_quote':'当前肺炎'}
        source=[{'document':'D1','page':0,'spans':[['S1','既往肺炎']]}]
        config=MagicMock();config._call.side_effect=[({},json.dumps({'accepted':False,'issues':[issue]})),({},'{"confirmed_1":true}')]
        verdict,_=review_analysis(config,source,'当前肺炎')
        self.assertFalse(verdict.accepted)
        config._call.side_effect=[({},json.dumps({'accepted':False,'issues':[issue,issue]})),({},'{"confirmed_1":true}')]
        with self.assertRaisesRegex(ValueError,'ANALYSIS_JUDGMENT_FORMAT'):review_analysis(config,source,'当前肺炎')

    def test_official_review_uses_bounded_strict_format(self):
        config=MagicMock();config.base_url='https://api.deepseek.com';config.model_id='deepseek-flash'
        empty={'category':'none','explanation':'','source_quote':'','draft_quote':''}
        response={'accepted':True,**{f'issue_{i}':empty for i in range(1,4)}}
        with patch('services.api.app.analysis_review.requests.post') as post:
            post.return_value.json.return_value={'usage':{'total_tokens':12},'choices':[{'message':{'tool_calls':[{
                'function':{'name':'deliver_review','arguments':json.dumps(response)}}]}}]}
            verdict,usage=review_analysis(config,[{'document':'D1','page':0,'spans':[['S1','合成原文']]}],'合成原文')
            self.assertTrue(verdict.accepted)
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'],3000)
            self.assertTrue(post.call_args.kwargs['json']['tools'][0]['function']['strict'])
            self.assertEqual(usage['request_usages'],[{'total_tokens':12}])
            config._call.assert_not_called()

    def test_rejected_draft_is_repaired_and_reviewed_before_delivery(self):
        class Script:
            def __init__(self):self.calls=0;self.reviews=0
            def complete(self,messages,allow_tools=False):
                self.calls+=1
                if self.calls==2:assert '原文复核未通过' in messages[-1]['content']
                return {'content':json.dumps({'text':'确诊肺炎' if self.calls==1 else '不能排除肺炎','evidence_refs':['S1'],'history_refs':[]})}
            def review_analysis(self,packed,text):
                self.reviews+=1
                return AnalysisReview(accepted=self.reviews==2,issues=[] if self.reviews==2 else [{'category':'qualifier','explanation':'不能排除不等于确诊'}])
        model=Script();tools=MagicMock();ref=str(uuid4())
        tools.execute.return_value={'status':'available','next_offset':None,'evidence':[{'evidence_id':ref,'text':'不能排除肺炎'}]}
        reply,_=run_agent([], '解读', [], tools,model=model,analysis_mode=True)
        self.assertEqual(reply['text'],'不能排除肺炎')
        self.assertEqual(reply['performance']['review_calls'],2)
        self.assertEqual(reply['performance']['model_calls'],4)

    def test_repeated_review_rejection_and_review_error_do_not_deliver(self):
        class Script:
            def complete(self,*args,**kwargs):return {'content':json.dumps({'text':'材料解读','evidence_refs':['S1'],'history_refs':[]})}
            def review_analysis(self,*args):return AnalysisReview(accepted=False,issues=[{'category':'unsupported','explanation':'无依据'}])
        tools=MagicMock();tools.execute.return_value={'status':'available','next_offset':None,'evidence':[{'evidence_id':str(uuid4()),'text':'合成原文'}]}
        with self.assertRaisesRegex(ValueError,'ANALYSIS_FIDELITY_REJECTED'):run_agent([], '解读', [], tools,model=Script(),analysis_mode=True)
        with patch.object(Script,'review_analysis',side_effect=RuntimeError('provider error')):
            with self.assertRaises(RuntimeError):run_agent([], '解读', [], tools,model=Script(),analysis_mode=True)

    def test_real_model_always_has_review_and_no_markdown_safety_bypass(self):
        self.assertTrue(callable(AgentModel.review_analysis))
        tools=MagicMock();tools.execute.return_value={'status':'available','next_offset':None,'evidence':[{'evidence_id':str(uuid4()),'text':'合成原文'}]}
        model=MagicMock();model.complete.return_value={'content':json.dumps({'text':'请自**行停**药','evidence_refs':['S1'],'history_refs':[]})}
        with self.assertRaisesRegex(ValueError,'UNSAFE_ANALYSIS'):run_agent([], '解读', [], tools,model=model,analysis_mode=True)

if __name__=='__main__':unittest.main()
