import json,os,unittest
from unittest.mock import patch
from services.api.app.guidance_context import care_priorities,select_guidance_knowledge
from services.api.app.guidance_quality import GuidanceQuality,guidance_requirements,enforce_guidance_requirements
from services.api.app.knowledge_assembler import KnowledgeAssembler
from services.api.app.contracts.knowledge import DiseaseCode
from services.api.app.report_llm import draft_report
from services.api.app.llm_extractor import OpenAiCompatibleExtractor
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.knowledge_retrieval import KnowledgeRetriever
from services.api.app.inline_citations import bind_citations

def assessment(**changes):
    return {**{key:True for key in GuidanceQuality.model_fields if key not in {'issues','explanations'}},'issues':[],**changes}

def draft(text='本次记录为肺炎。',quote=None):
    return {'sections':[{'section_type':section,'claims':[]} for section in SECTION_TYPES],'actions':[],
        'patient_analysis':{'text':text,'evidence_refs':['S1'],'history_refs':[],
            'knowledge_refs':[],'citations':[{'quote':quote or text,'source_refs':['S1']}]}}

class GuidanceGenerationTests(unittest.TestCase):
    def test_summary_cannot_pass_as_full_report_even_when_model_says_all_true(self):
        # Synthetic analogue of the observed one-paragraph report, no medical data.
        material=('诊断股骨头坏死。手术髋关节置换。费用合计。出院医嘱扶拐复诊。\n')*60
        knowledge=[{'entry_id':'HJ-S1-01','slot':'S1'},{'entry_id':'HJ-S11-01','slot':'S11'},
                   {'entry_id':'TY-COST-04','slot':'TY'}]
        requirements=guidance_requirements(material,knowledge)
        brief=draft('本次诊断、手术、费用和出院医嘱都在这里。'*20)
        quality=enforce_guidance_requirements(GuidanceQuality.model_validate(assessment()),brief,
                                              {'reading_requirements':requirements})
        self.assertFalse(quality.accepted)
        self.assertFalse(quality.detail_sufficient)
        self.assertFalse(quality.readable_structure)
        self.assertFalse(quality.explanation_clear)
        self.assertFalse(quality.treatment_understood)
        self.assertFalse(quality.costs_understood)

    def test_short_single_topic_material_does_not_require_padded_full_report(self):
        requirements=guidance_requirements('费用总额120元。')
        quality=enforce_guidance_requirements(GuidanceQuality.model_validate(assessment()),draft(),
                                              {'reading_requirements':requirements})
        self.assertTrue(quality.accepted)
        self.assertEqual(requirements['min_body_chars'],0)

    def test_detailed_cited_report_passes_presentation_floor(self):
        material=('诊断肺炎。治疗用药。费用结算。出院医嘱复诊。')*100
        body='我看过这次的资料了。\n\n'+'\n\n'.join(
            f'{i}. **本次情况{i}**\n'+('解释本次事实及具体核对方向。'*16) for i in range(1,5))
        full=draft(body)
        full['patient_analysis']['knowledge_refs']=['FY-S1-01','TY-COST-04']
        requirements=guidance_requirements(material,[{'entry_id':'FY-S1-01','slot':'S1'},
                                                    {'entry_id':'TY-COST-04','slot':'TY'}])
        self.assertTrue(enforce_guidance_requirements(GuidanceQuality.model_validate(assessment()),full,
            {'reading_requirements':requirements}).accepted)

    def test_hip_references_are_resolvable_with_scope_and_approval_state_preserved(self):
        from services.api.app.insight_detector import infer_disease_code
        self.assertEqual(infer_disease_code('股骨头缺血性坏死，髋关节置换术后'),DiseaseCode.hj)
        retriever=KnowledgeRetriever()
        result=retriever.search('股骨头坏死 髋关节置换',case_text='成人股骨头坏死')
        self.assertTrue(any(item['disease_code']=='HJ' for item in result['results']))
        self.assertTrue(all(item['source_path'].startswith('docs/medical/knowledge/') for item in result['results']))
        excluded=retriever.resolve_references(['HJ-S1-01'],case_text='假体周围感染')
        self.assertEqual(excluded['results'],[])
        self.assertEqual(KnowledgeAssembler().select(DiseaseCode.hj,patient_visible=True).allowed,[])
        assembler=KnowledgeAssembler()
        entries=assembler.select(DiseaseCode.hj,patient_visible=False).allowed+assembler.select(DiseaseCode.ty,patient_visible=False).allowed
        selected=select_guidance_knowledge(entries,{'candidates':{'candidates':[{'raw_value':'股骨头坏死'}]}},
                                          '股骨头坏死，髋关节置换，抗凝预防血栓，费用医保结算。',None)
        self.assertIn('HJ-S11-01',{item['entry_id'] for item in selected})
        no_operation=guidance_requirements('肺炎抗感染治疗',[
            {'entry_id':'FY-S1-01','slot':'S1'},{'entry_id':'FY-S11-01','slot':'S11'}])
        self.assertFalse(any(group['theme']=='treatment' for group in no_operation['knowledge_groups']))

    def test_quote_terminal_punctuation_can_be_corrected_without_changing_words(self):
        text='复诊日期请联系诊疗团队确认；再准备已有影像。'
        links=bind_citations(text,[{'quote':'复诊日期请联系诊疗团队确认。','source_refs':['S1']}],{},['S1'],[])
        self.assertEqual(links[0]['quote'],'复诊日期请联系诊疗团队确认；')
        for quote,body in [('复诊日期请自行改成明天。',text),
                           ('复诊日期请联系诊疗团队确认。','复诊日期请联系诊疗团队确认；复诊日期请联系诊疗团队确认；')]:
            with self.assertRaisesRegex(ValueError,'CITATION_ANCHOR_NOT_UNIQUE'):
                bind_citations(body,[{'quote':quote,'source_refs':['S1']}],{},['S1'],[])
    def test_priorities_retain_only_actual_quotes_and_never_assert_verified_pain(self):
        row={'label':'EXP_TERMINOLOGY_BARRIER','evidence_quote':'诊断肺炎',
            'rationale':'解释术语','suggested_action':'说明一般含义','knowledge_refs':['FY-S1-01','forged']}
        result=care_priorities({'status':'completed','candidates':[row,{**row,'evidence_quote':'不存在的病情'}]},
                               '诊断肺炎',['FY-S1-01'])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['knowledge_refs'],['FY-S1-01'])
        self.assertEqual(result[0]['status'],'candidate_requires_confirmation')
        self.assertEqual(care_priorities({'status':'failed','candidates':[row]},'诊断肺炎',[]),[])

    def test_reference_selection_covers_themes_and_preserves_full_source_text(self):
        assembler=KnowledgeAssembler()
        for code,name in [(DiseaseCode.fx,'骨折'),(DiseaseCode.fy,'肺炎'),(DiseaseCode.tn,'糖尿病')]:
            entries=assembler.select(code,patient_visible=False).allowed
            selected=select_guidance_knowledge(entries,{'candidates':{'candidates':[{'raw_value':name}]}},name,{'concern':'担心恢复'})
            self.assertLessEqual(len(selected),12)
            self.assertTrue(any(item['slot']=='S1' for item in selected))
            self.assertTrue(any(item['slot'] in {'S5','S6','S7'} for item in selected))
            original={e.entry_id:e for e in entries}
            self.assertTrue(all(item['content']==original[item['entry_id']].content for item in selected))
            self.assertTrue(all(not original[item['entry_id']].numeric_pending_review for item in selected))

    def run_report(self,responses):
        with patch.dict(os.environ,{'LLM_BASE_URL':'https://qianfan.baidubce.com/v2','LLM_API_KEY':'synthetic','LLM_MODEL_ID':'glm-5.3-flash'}), \
             patch.object(OpenAiCompatibleExtractor,'_call',side_effect=[({'usage':{'total_tokens':10}},json.dumps(item)) for item in responses]) as call:
            result=draft_report('诊断肺炎',[],None,analysis_sources=[{'document':'D1','page':0,'spans':[['S1','诊断肺炎']]}],
                                care_priorities=[{'label':'EXP_TERMINOLOGY_BARRIER','status':'candidate_requires_confirmation'}])
        return result,call

    def test_quality_review_repairs_insufficient_explanation_once_and_records_cost(self):
        result,call=self.run_report([draft(),assessment(explanation_clear=False,issues=['没有解释术语']),
                                    draft('本次记录为肺炎，术语的含义需要结合提供的知识说明。'),assessment()])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(call.call_count,4)
        self.assertEqual(result['usage_metadata']['total_tokens'],40)
        self.assertEqual(len(result['usage_metadata']['guidance_quality_reviews']),2)
        self.assertEqual(call.call_args.kwargs['timeout'],(10,60))

    def test_quality_failure_is_not_marked_as_completed(self):
        bad=assessment(recovery_actionable=False,issues=['只有笼统安慰，没有准备方向'])
        result,_=self.run_report([draft(),bad,draft(),bad])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['error_code'],'REPORT_GUIDANCE_QUALITY_REJECTED')

    def test_optional_polishing_does_not_override_all_passing_quality_criteria(self):
        self.assertTrue(GuidanceQuality.model_validate(assessment(issues=['可选：进一步精简一句话'])).accepted)

    def test_bad_quote_is_repaired_before_quality_review(self):
        result,call=self.run_report([draft(quote='正文中没有这句话'),
                                    {'repairs':[{'citation_index':0,'quote':'本次记录为肺炎。'}]},assessment()])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(call.call_count,3)

    def test_exact_reference_resolution_preserves_version_and_filters_pending_numbers(self):
        docs=[{'entry_id':'FY-S1-01','disease_code':'FY','content':'知识正文','numeric_pending_review':False},
              {'entry_id':'FY-S4-01','disease_code':'FY','content':'数值待核对','numeric_pending_review':True}]
        for item in docs:item['title']='说明'
        retriever=KnowledgeRetriever(docs,version='v-test')
        result=retriever.resolve_references(['FY-S4-01','FY-S1-01','forged'],case_text='肺炎')
        self.assertEqual([item['entry_id'] for item in result['results']],['FY-S1-01'])
        self.assertEqual(result['results'][0]['version'],'v-test')
