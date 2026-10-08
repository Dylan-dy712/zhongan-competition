import unittest,json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
from services.api.app.analysis_partial import verified_partial
from services.api.app.analysis_review import AnalysisReview
from services.api.app.conversation_agent import run_agent

DRAFT='概述。\n\n1. **费用**\n\n个人现金1000元。\n\n2. **不能排除感染**\n\n原文不能排除感染，不能视为确诊。'

class PartialTests(unittest.TestCase):
    def test_removes_whole_unverified_point_and_keeps_qualified_words(self):
        issue=SimpleNamespace(category='payment',draft_quote='个人现金1000元')
        packed=[{'document':'D1','page':0,'spans':[['S1','合计金额:120.00']]}]
        result=verified_partial(DRAFT,[issue],packed,{'S1':'ref'},['ref'])
        self.assertNotIn('1000',result)
        self.assertIn('不能排除感染，不能视为确诊',result)
        self.assertIn('合计金额:120.00',result)
        self.assertIn('1. **不能排除感染**',result)
        self.assertIn('需要查看原材料确认',result)

    def test_does_not_add_uncited_money_or_relabeled_personal_total(self):
        issue=SimpleNamespace(category='payment',draft_quote='个人现金1000元')
        for text,refs in [('合计金额:120.00',[]),('个人支付总金额:120.00',['ref'])]:
            result=verified_partial(DRAFT,[issue],[{'document':'D1','page':0,'spans':[['S1',text]]}],{'S1':'ref'},refs)
            self.assertNotIn('120.00',result)

    def test_no_safe_points_or_unlocatable_quote_fails_closed(self):
        for text,quote in [('1. **错误**\n错误','错误'),(DRAFT,'不存在的引句')]:
            self.assertIsNone(verified_partial(text,[SimpleNamespace(category='scope',draft_quote=quote)],[],{},[]))

    def test_partial_must_pass_another_independent_review(self):
        for final_accepted in [True,False]:
            class Script:
                def __init__(self):self.reviews=0
                def complete(self,*args,**kwargs):return {'content':json.dumps({'text':DRAFT,'evidence_refs':['S1'],'history_refs':[]})}
                def review_analysis(self,packed,text):
                    self.reviews+=1
                    if self.reviews==3:
                        assert '1000' not in text
                        return AnalysisReview(accepted=final_accepted,issues=[] if final_accepted else [{'category':'unsupported','explanation':'仍有错误','draft_quote':'感染'}])
                    return AnalysisReview(accepted=False,issues=[{'category':'payment','explanation':'金额不符','draft_quote':'个人现金1000元'}])
            tools=MagicMock();tools.execute.return_value={'status':'available','next_offset':None,'evidence':[{'evidence_id':str(uuid4()),'text':'合计金额:120.00'}]}
            model=Script()
            if final_accepted:
                reply,_=run_agent([], '解读', [], tools,model=model,analysis_mode=True)
                self.assertTrue(reply['performance']['partial_delivery'])
                self.assertEqual(reply['performance']['review_calls'],3)
                self.assertNotIn('1000',reply['text'])
            else:
                with self.assertRaisesRegex(ValueError,'ANALYSIS_FIDELITY_REJECTED'):run_agent([], '解读', [], tools,model=model,analysis_mode=True)

if __name__=='__main__':unittest.main()
