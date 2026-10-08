import unittest
from services.api.app.analysis_review import literal_scope_issues

class LiteralScopeTests(unittest.TestCase):
    def test_numbers_and_reference_headers_do_not_authorize_normal_conclusion(self):
        source=[{'document':'D1','page':0,'spans':[['S1','肺炎支原体IgM 0.15COI。'],['S2','参考范围：未提供。']]}]
        self.assertEqual(len(literal_scope_issues(source,'几项抗体也都在参考范围内。')),1)
        self.assertEqual(len(literal_scope_issues(source,'**数值在正常范围内**。')),1)

    def test_explicit_recorded_evaluation_and_cautious_language_are_retained(self):
        source=[{'document':'D1','page':0,'spans':[['S1','记录意见：指标在参考范围内。']]}]
        self.assertEqual(literal_scope_issues(source,'记录写到在参考范围内。'),[])
        source[0]['spans'][0][1]='肺炎支原体IgM 0.15COI。'
        self.assertEqual(literal_scope_issues(source,'没有参考范围，不能认为这些指标都在参考范围内。'),[])
        self.assertEqual(literal_scope_issues(source,'不能据此判断数值在正常范围内。'),[])

if __name__=='__main__':unittest.main()
