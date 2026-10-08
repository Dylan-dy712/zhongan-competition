import unittest
from uuid import uuid4
from services.api.app.material_report import build_material_sections


class MaterialReportTests(unittest.TestCase):
    def report(self, claim):
        return {'sections': [{'section_type': 'cost_explanation', 'claims': [claim]}]}

    def test_verified_amount_is_visible_with_original_evidence(self):
        ref=str(uuid4())
        sections=build_material_sections(self.report({'text':'医疗总费用：120元','claim_type':'case_fact',
            'evidence_refs':[ref]}),{ref:'医疗总费用：120元'},{})
        cost=next(s for s in sections if s['section_type']=='cost_explanation')
        self.assertEqual(cost['items'][0],{'text':'医疗总费用：120元','kind':'checked','evidence_refs':[ref]})
        self.assertEqual(cost['pending_count'],0)

    def test_wrong_amount_is_withheld_and_original_qualifiers_survive(self):
        ref=str(uuid4());quote='疑似费用记录：医疗总费用120元，不能确认结算范围。'
        sections=build_material_sections(self.report({'text':'你已支付999元','claim_type':'case_fact',
            'evidence_refs':[ref],'review_status':'approved'}),{ref:quote},{})
        cost=next(s for s in sections if s['section_type']=='cost_explanation')
        self.assertEqual(cost['pending_count'],1)
        self.assertEqual(cost['items'],[{'text':quote,'kind':'source','evidence_refs':[ref]}])
        self.assertNotIn('999',str(sections))

    def test_unknown_and_cross_case_evidence_cannot_make_content_visible(self):
        sections=build_material_sections(self.report({'text':'治疗已完成','claim_type':'case_fact',
            'evidence_refs':[str(uuid4())]}),{}, {})
        self.assertFalse(any(s['items'] for s in sections))

    def test_professional_and_service_advice_do_not_bypass_review(self):
        for kind in ['professional_explanation','service_suggestion','to_confirm']:
            with self.subTest(kind=kind):
                sections=build_material_sections(self.report({'text':'自行停药后保证康复','claim_type':kind}),{}, {})
                self.assertFalse(any(s['items'] for s in sections))
                self.assertNotIn('保证康复',str(sections))

    def test_user_statement_remains_separate_from_medical_evidence(self):
        sections=build_material_sections(self.report({'text':'我担心费用','claim_type':'patient_statement',
            'source_refs':['user:1']}),{}, {'user:1':'我担心费用'})
        item=next(s for s in sections if s['section_type']=='cost_explanation')['items'][0]
        self.assertEqual(item['evidence_refs'],[])
        self.assertEqual(item['text'],'我担心费用')
