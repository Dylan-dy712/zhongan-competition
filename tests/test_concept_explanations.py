import unittest
from unittest.mock import Mock,patch
from uuid import uuid4

from services.api.app.guidance_quality import GuidanceQuality,ExplanationEvidence,enforce_explanation_evidence,guidance_requirements,review_guidance_quality
from services.api.app.guidance_context import select_guidance_knowledge
from services.api.app.knowledge_assembler import KnowledgeAssembler
from services.api.app.contracts.knowledge import DiseaseCode
from services.api.app.web_knowledge import safe_concepts,supplement_knowledge,WebKnowledge
from services.api.app.conversation_agent import CareTools
from services.api.app.report_llm import PROMPT_VERSION


def verdict(**changes):
    return GuidanceQuality(**{k:True for k in GuidanceQuality.model_fields if k not in {'issues','explanations'}},**changes)


class ConceptExplanationTests(unittest.TestCase):
    def test_public_synonyms_and_recorded_treatment_share_the_query_budget(self):
        # Entirely invented clinical labels, not production records.
        names=['诊断：乳腺恶性肿瘤；骨质疏松','诊断：乳癌；恶性肿瘤靶向治疗']
        material='\n'.join(names)
        fields={'candidates':[{'fact_type':'diagnosis','raw_value':x,'evidence_quote':x,'assertion':'present'} for x in names]}
        self.assertEqual(safe_concepts(fields,material),[
            {'term':'乳腺癌','slot':'S1'},{'term':'靶向治疗','slot':'S11'},{'term':'骨质疏松症','slot':'S1'}])
        service=Mock(enabled=True,per_report=2)
        service.search.return_value={'status':'available','results':[],'calls':1}
        with patch('services.api.app.web_knowledge.WebKnowledge',return_value=service):
            _,meta=supplement_knowledge([],fields,material)
        self.assertEqual([c.args[0]['term'] for c in service.search.call_args_list],['乳腺癌','靶向治疗'])
        self.assertEqual(meta['calls'],2)

    def test_only_explicit_treatment_word_is_mapped_from_medication_record(self):
        material='记录：靶向治疗。曲妥珠单抗。'
        field={'candidates':[{'fact_type':'medication','raw_value':raw,'evidence_quote':raw,'assertion':'present'}
                             for raw in ('靶向治疗','曲妥珠单抗')]}
        self.assertEqual(safe_concepts(field,material),[{'term':'靶向治疗','slot':'S11'}])
        field['candidates'][0]['assertion']='historical'
        self.assertEqual(safe_concepts(field,material),[])

    def test_generic_breast_and_treatment_queries_can_use_original_nci_sources(self):
        service=WebKnowledge()
        for term,title,slot in [('乳腺癌','Breast Cancer Types','S1'),('靶向治疗','Targeted Therapy to Treat Cancer','S11')]:
            content=title+'\n'+'This is a synthetic public definition for retrieval testing, not personal advice. '*3
            docs=service.references([{'Title':title,'Url':'https://www.cancer.gov/types/test','Content':content}],{'term':term,'slot':slot},1000000)
            self.assertEqual(len(docs),1)
            self.assertEqual(docs[0]['slot'],slot)

    def test_category_label_selects_the_actual_definition_and_treatment_needs_explanation(self):
        entries=KnowledgeAssembler().select(DiseaseCode.ty,patient_visible=False).allowed
        selected=select_guidance_knowledge(entries,{'candidates':{}},'收费单：药费乙类，检查甲类。',None)
        self.assertIn('TY-COST-01',{x['entry_id'] for x in selected})
        groups=guidance_requirements('门诊诊断乳腺癌，靶向治疗，收费单乙类。',[{'slot':'S11','entry_id':'WEB-TEST'}])['knowledge_groups']
        self.assertIn({'theme':'treatment','one_of':['WEB-TEST']},groups)

    def fixture(self):
        meaning='靶向治疗的一般含义是针对癌细胞生长相关的特定蛋白。'
        relation='这份虚构记录写的是安排靶向治疗，不证明已经完成注射。'
        help_text='可以把原有处方带到复诊，确认本次治疗和后续预约的安排。'
        draft={'patient_analysis':{'text':meaning+relation+help_text,
               'citations':[{'quote':meaning,'source_refs':['PUBLIC-TREATMENT']}],
               'knowledge_refs':['PUBLIC-TREATMENT']}}
        proof=ExplanationEvidence(theme='treatment',meaning_quote=meaning,case_connection_quote=relation,help_quote=help_text)
        context={'reading_requirements':{'knowledge_groups':[{'theme':'treatment','one_of':['PUBLIC-TREATMENT']}]}}
        return draft,proof,context

    def test_all_true_flags_and_reference_ids_do_not_make_recitation_an_explanation(self):
        draft,_,context=self.fixture()
        draft['patient_analysis']['text']='开了靶向药物，具体意思请医生解释。'
        checked=enforce_explanation_evidence(verdict(),draft,context)
        self.assertFalse(checked.accepted)
        self.assertFalse(checked.treatment_understood)

    def test_actual_explanation_connection_and_help_with_sentence_reference_pass(self):
        draft,proof,context=self.fixture()
        self.assertTrue(enforce_explanation_evidence(verdict(explanations=[proof]),draft,context).accepted)

    def test_fabricated_quotes_and_wrong_theme_citation_are_rejected(self):
        draft,proof,context=self.fixture()
        for changed,body in [(proof.model_copy(update={'meaning_quote':'正文中没有这句概念解释。'}),draft),
                             (proof,{**draft,'patient_analysis':{**draft['patient_analysis'],'citations':[{'quote':proof.meaning_quote,'source_refs':['UNRELATED']}]}}),
                             (proof.model_copy(update={'help_quote':proof.case_connection_quote}),draft)]:
            self.assertFalse(enforce_explanation_evidence(verdict(explanations=[changed]),body,context).accepted)

    def test_model_positive_verdict_must_include_actual_explanation_evidence(self):
        draft,_,context=self.fixture()
        client=Mock();client._call.return_value=({'usage':{}},verdict().model_dump_json())
        checked,_=review_guidance_quality(client,draft,context,timeout=(10,60))
        self.assertFalse(checked.accepted)
        prompt=client._call.call_args.args[0][0]['content']
        self.assertIn('具体意义请医生解释',prompt)
        self.assertIn('meaning_quote',prompt)

    def test_user_request_refreshes_an_old_draft_policy_but_reuses_a_current_one(self):
        for outdated in (True,False):
            case,actor,conversation=uuid4(),uuid4(),uuid4()
            conn=Mock()
            conn.execute.side_effect=[Mock(fetchall=Mock(return_value=[{'document_id':uuid4(),'document_version':1}])),
                                      Mock(fetchone=Mock(return_value={'exists':1} if outdated else None))]
            with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':case}), \
                 patch('services.api.app.conversation_agent.create_analysis_run',return_value=(Mock(run_id=uuid4(),status='queued'),True)) as create:
                result=CareTools(conn,actor,conversation).execute('start_analysis','{}')
            self.assertEqual(result['status'],'queued')
            self.assertEqual(create.call_args.kwargs['force_new'],outdated)
            sql,args=conn.execute.call_args.args
            self.assertIn('prompt_version<>%s',sql)
            self.assertEqual(args,(case,PROMPT_VERSION))
