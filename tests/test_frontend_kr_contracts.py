import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from uuid import UUID
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from services.api.app.document_quality import inspect_photo, classify_material
from services.api.app.inline_citations import bind_citations, InlineCitation
from services.api.app.worker import ocr_page, evidence_for_page
from services.api.app.quality_demo import demo_snapshot, demo_recommendations
from services.api.app.quality_profiles import ProfileMatchRequest
from services.api.app.main import app, current_actor, database


class Ocr:
    def recognize(self, *args):
        return {'text':'医疗发票\n金额：123.00', 'blocks':[
            {'text':'医疗发票','metadata':{'confidence_score':.99},'bbox':[.1,.1,.8,.2]},
            {'text':'金额：123.00','metadata':{'confidence_score':.4},'bbox':[.1,.3,.8,.4]}],
            'request_id':'synthetic','angle':0}


class FrontendKrContracts(unittest.TestCase):
    def photo(self, size=(900,1200)):
        image=Image.new('RGB',size,'white');draw=ImageDraw.Draw(image)
        for y in range(30,size[1]-30,35):draw.text((30,y),'SYNTHETIC MEDICAL DOCUMENT 2026',fill='black')
        out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()

    def test_partial_invoice_is_named_but_amount_warned(self):
        result=inspect_photo(self.photo(),Ocr)
        self.assertEqual(result['material_type'],'医疗发票')
        self.assertEqual(result['status'],'warning')
        self.assertIn('部分文字',result['issues'][-1])

    def test_readable_text_with_large_white_margin_is_not_called_blurry(self):
        image=Image.new('RGB',(1200,1600),'white')
        out=io.BytesIO();image.save(out,format='PNG')
        text='医疗发票 金额123.00元 就医日期2026年10月12日'
        factory=lambda:SimpleNamespace(recognize=lambda *args:{'text':text,'blocks':[
            {'text':text,'metadata':{'confidence_score':.99}}]})
        result=inspect_photo(out.getvalue(),factory)
        self.assertEqual(result['status'],'checked')
        self.assertEqual(result['issues'],[])

    def test_no_ocr_cannot_infer_blur_from_blank_margins(self):
        image=Image.new('RGB',(1200,1600),'white')
        out=io.BytesIO();image.save(out,format='PNG')
        result=inspect_photo(out.getvalue())
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['issues'],[])

    def test_ocr_failure_does_not_claim_readable(self):
        result=inspect_photo(self.photo())
        self.assertEqual(result['ocr_status'],'unavailable')
        self.assertNotEqual(result['status'],'checked')
        self.assertEqual(result['type_certainty'],'unknown')

    def test_low_resolution_and_ambiguous_type(self):
        result=inspect_photo(self.photo((200,250)),Ocr)
        self.assertTrue(any('分辨率' in s for s in result['issues']))
        self.assertEqual(classify_material('医疗发票\n出院小结')[1],'unknown')

    def test_uncertain_amount_never_enters_evidence_or_facts_text(self):
        page=ocr_page(b'',900,1200,{'metadata':{},'page_index':0},Ocr())
        self.assertEqual(page['text'],'医疗发票')
        self.assertEqual(page['metadata']['photo_quality']['uncertain_lines'],1)
        rows=evidence_for_page({'document_id':'d','document_version':1},page)
        self.assertEqual([r['text'] for r in rows],['医疗发票'])
        self.assertEqual(page['blocks'][1]['text'],'金额：123.00')  # audit preserved

    def test_citations_require_unique_literal_anchor_and_authorized_source(self):
        cite=InlineCitation(quote='费用120元。',source_refs=['S1'])
        result=bind_citations('费用**120元**。',[cite],{'S1':'evidence-1'},['evidence-1'],[])
        self.assertEqual(result[0]['source_refs'],['evidence-1'])
        for text,aliases in [('费用120元。费用120元。',{'S1':'evidence-1'}),('费用120元。',{'S1':'someone-else'}),('费用130元。',{'S1':'evidence-1'})]:
            with self.assertRaises(ValueError):bind_citations(text,[cite],aliases,['evidence-1'],[])

    def test_three_disease_demo_is_complete_but_never_ranked(self):
        snapshot=demo_snapshot()
        self.assertEqual(snapshot['data_origin'],'synthetic')
        self.assertEqual(len(snapshot['profiles']),15)
        for disease in ('FY','FX','TN'):
            profiles=[p for p in snapshot['profiles'] if p['cohort_filters']['disease_group']==disease]
            self.assertEqual(len(profiles),5)
            self.assertTrue(all(sum(m['value'] is not None for m in p['metrics'])>=5 for p in profiles))
            request=ProfileMatchRequest(disease_group=disease,treatment_group='demo-care@v1',risk_group='demo-low',payer_group='demo-payer',needs=[{'need_id':'a','metric_name':'cost_level'},{'need_id':'b','metric_name':'guidance_completeness'}])
            results=demo_recommendations(request)['results']
            self.assertTrue(all(len(r['match_reasons'])>=2 and not r['ranking_allowed'] and r['rank'] is None for r in results))

    def test_quality_route_checks_run_and_case_together(self):
        actor=UUID('00000000-0000-4000-8000-000000000001')
        case=UUID('00000000-0000-4000-8000-000000000002')
        run=UUID('00000000-0000-4000-8000-000000000003')
        conn=MagicMock();conn.execute.return_value.fetchall.return_value=[]
        app.dependency_overrides[current_actor]=lambda:actor
        app.dependency_overrides[database]=lambda:conn
        try:
            with TestClient(app) as client, patch('services.api.app.main.get_analysis_run',autospec=True) as read:
                read.return_value=SimpleNamespace(case_id=case)
                self.assertEqual(client.get(f'/v1/cases/{case}/material-quality?run_id={run}').status_code,200)
                read.assert_called_once_with(conn,actor_id=actor,run_id=run)
                read.return_value=SimpleNamespace(case_id=actor)
                self.assertEqual(client.get(f'/v1/cases/{case}/material-quality?run_id={run}').status_code,404)
        finally:app.dependency_overrides.clear()

    def test_inspection_rechecks_consent_after_ocr(self):
        actor=UUID('00000000-0000-4000-8000-000000000001')
        app.dependency_overrides[current_actor]=lambda:actor
        app.dependency_overrides[database]=lambda:MagicMock()
        try:
            with TestClient(app) as client, patch('services.api.app.main.chats.available_subjects',side_effect=[[{'subject_id':actor}],[]]), patch('services.api.app.main.inspect_photo',return_value={'status':'checked'}) as inspect:
                response=client.post('/v1/materials/inspect',data={'subject_id':str(actor)},files={'file':('synthetic.png',self.photo(),'image/png')})
                self.assertEqual(response.status_code,403)
                inspect.assert_called_once()
        finally:app.dependency_overrides.clear()

    def test_inspection_denies_unconsented_subject_before_ocr(self):
        actor=UUID('00000000-0000-4000-8000-000000000001')
        app.dependency_overrides[current_actor]=lambda:actor
        app.dependency_overrides[database]=lambda:MagicMock()
        try:
            with TestClient(app) as client, patch('services.api.app.main.chats.available_subjects',return_value=[]), patch('services.api.app.main.inspect_photo') as inspect:
                response=client.post('/v1/materials/inspect',data={'subject_id':str(actor)},files={'file':('synthetic.png',self.photo(),'image/png')})
                self.assertEqual(response.status_code,403)
                inspect.assert_not_called()
        finally:app.dependency_overrides.clear()


if __name__=='__main__':unittest.main()
