import copy,json,os,tempfile,unittest
from unittest.mock import patch,MagicMock
from uuid import uuid4
from services.api.app.judge_experience import (eligible_context,question_key,prepare_variant,publish_bundle,
    read_bundle,artifact_path,bind_draft,select_variant,prepared_answer)
from services.api.app.report_builder import SECTION_TYPES


class JudgeExperienceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'ZHONGAN_JUDGE_RECOGNITION_ROOT':tmp.name});env.start();self.addCleanup(env.stop)
        identity=patch('services.api.app.judge_experience.version_identity',return_value='b'*64);identity.start();self.addCleanup(identity.stop)
        self.ref=str(uuid4());self.rows=[{'evidence_id':self.ref,'source_hash':'a'*64,'page_index':0,'text_value':'合成材料原文。','parser_version':'synthetic'}]
        body='根据合成资料，保留材料中的不确定限定，复诊时向诊疗团队核对。'*20
        self.reply={'text':body,'evidence_refs':[self.ref],'knowledge_refs':[],'history_refs':[],
            'citations':[{'quote':body,'source_refs':[self.ref]}],
            'performance':{'source_read_complete':True,'review_calls':1,'partial_delivery':False},'guidance_delivery':{'status':'passed'}}
        self.report={'status':'completed','draft':{'sections':[{'section_type':s,'claims':[{'text':'合成说明',
            'claim_type':'case_fact','evidence_quote':'合成材料原文。','source_refs':['D1']}]} for s in SECTION_TYPES],'actions':[]},'usage_metadata':{}}
        self.insights={'status':'completed','candidates':[],'usage_metadata':{},'error_code':None}
        self.manifest={'sample_id':'synthetic','version':'v1','documents':[{'sha256':'a'*64}]}

    def variants(self):
        return [prepare_variant(self.reply,self.rows,self.report,self.insights,str(i),[]) for i in range(3)]

    def test_corpus_has_no_case_evidence_ids_and_rebinds_every_citation(self):
        publish_bundle(self.manifest,['分析固定示例'],self.rows,self.variants())
        self.assertNotIn(self.ref,artifact_path().read_text(encoding='utf8'))
        bundle=read_bundle();variant=select_variant(bundle,'same-run')
        self.assertEqual(variant,select_variant(bundle,'same-run'))
        self.assertEqual(variant['report']['draft']['sections'][0]['claims'][0]['source_refs'],[])
        fresh=str(uuid4());rows=[{**self.rows[0],'evidence_id':fresh}]
        reply=bind_draft(variant,rows)
        self.assertEqual(reply.evidence_refs,[fresh]);self.assertEqual(reply.citations[0].source_refs,[fresh])
        with self.assertRaises(KeyError):bind_draft(variant,[{**rows[0],'text_value':'不同材料'}])

    def test_personal_inputs_memory_and_ordinary_accounts_stay_live(self):
        context={'judge_demo':True,'sample_id':'synthetic','sample_version':'v1'};allowed={question_key('分析固定示例')}
        self.assertTrue(eligible_context(context,['分析固定示例\n（重新分析当前材料）'],None,[],allowed))
        for c,q,m,p in [(context,['我现在疼痛加重'],None,[]),({},['分析固定示例'],None,[]),
            ({**context,'new_symptom':'合成症状'},['分析固定示例'],None,[]),
            (context,['分析固定示例'],{'items':['memory']},[]),(context,['分析固定示例'],None,[{'statement':'个人补充'}])]:
            self.assertFalse(eligible_context(c,q,m,p,allowed))
        self.assertIsNone(prepared_answer(MagicMock(),None))

    def test_unverified_variants_and_tampered_bundle_never_publish_or_load(self):
        reply=copy.deepcopy(self.reply);reply['performance']['review_calls']=0
        with self.assertRaises(ValueError):prepare_variant(reply,self.rows,self.report,self.insights,'bad',[])
        reply=copy.deepcopy(self.reply);reply['history_refs']=[str(uuid4())]
        with self.assertRaises(ValueError):prepare_variant(reply,self.rows,self.report,self.insights,'bad',[])
        publish_bundle(self.manifest,['分析固定示例'],self.rows,self.variants())
        payload=json.loads(artifact_path().read_text(encoding='utf8'));payload['data']['variants'][0]['draft']['text']='changed'
        artifact_path().write_text(json.dumps(payload))
        self.assertIsNone(read_bundle())

    def test_worker_prepared_path_does_not_call_any_generation_provider(self):
        from services.api.app.worker import analyze_models
        fields={'status':'partial','candidates':{'candidates':[],'cost_lines':[]},'personnel':[],
            'structured_documents':[{'document_id':str(uuid4()),'page_index':0,'status':'partial','prediction':{'fields':{},'confidence':{},'evidence':{}}}],
            'usage_metadata':{'strategy':'C','document_extractions':[]}}
        variant=self.variants()[0]
        with patch('services.api.app.worker.OpenAiCompatibleExtractor',side_effect=AssertionError('No live model')),patch('services.api.app.worker.draft_report',side_effect=AssertionError('No live report')):
            result=analyze_models('合成材料',[],{}, {},[],{},lambda _:None,document_models=fields,
                prepared_experience={'report':variant['report'],'insights':variant['insights'],'variant':'0'})
        self.assertEqual(result[0]['status'],'partial')
        self.assertEqual(result[-1]['judge_experience']['duration_ms'],8000)
