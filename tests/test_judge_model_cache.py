import copy,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from uuid import uuid4
from services.api.app.judge_model_cache import write_models,read_models,model_identity,artifact_path
from services.api.app.worker import analyze_models


class JudgeModelCacheTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        env=patch.dict(os.environ,{'ZHONGAN_JUDGE_RECOGNITION_ROOT':tmp.name,'LLM_PROVIDER':'synthetic',
            'LLM_MODEL_ID':'synthetic','LLM_BASE_URL':'http://127.0.0.1','LLM_API_KEY':'synthetic'})
        env.start();self.addCleanup(env.stop)
        self.documents=[({'source_hash':'a'*64,'document_id':uuid4()},[{'page_index':0,'text':'合成材料原文。',
            'content_hash':'b'*64,'parser_version':'synthetic'}])]
        self.knowledge=[SimpleNamespace(entry_id='K1',title='合成知识',content='一般说明',anchoring={})]
        self.fields={'status':'completed','candidates':{'candidates':[],'cost_lines':[]},'personnel':[],
                     'raw_output':{'private':'not persisted'},'usage_metadata':{'total_tokens':999}}
        self.insights={'status':'completed','candidates':[]}

    def prepare(self):return write_models(self.documents,self.knowledge,'profile',self.fields,self.insights)

    def test_reused_material_has_no_account_evidence_or_old_token_usage(self):
        identity=self.prepare();second=copy.deepcopy(self.documents);second[0][0]['document_id']=uuid4()
        self.assertEqual(model_identity(second,self.knowledge,'profile'),identity)
        fields,insights=read_models(second,self.knowledge,'profile')
        self.assertEqual(fields['usage_metadata']['total_tokens'],0)
        self.assertEqual(fields['usage_metadata']['material_preprocessing'],'preloaded')
        self.assertIsNone(fields['raw_output'])
        data=artifact_path(identity).read_text(encoding='utf-8')
        self.assertNotIn(str(self.documents[0][0]['document_id']),data)
        self.assertNotIn('not persisted',data)

    def test_changed_sources_parser_model_knowledge_or_corruption_miss(self):
        identity=self.prepare()
        changed=copy.deepcopy(self.documents);changed[0][1][0]['text']='变化后的原文。'
        self.assertIsNone(read_models(changed,self.knowledge,'profile'))
        self.assertIsNone(read_models(self.documents,self.knowledge,'new-profile'))
        with patch.dict(os.environ,{'LLM_MODEL_ID':'different'}):
            self.assertIsNone(read_models(self.documents,self.knowledge,'profile'))
        changed_knowledge=[SimpleNamespace(entry_id='K1',title='合成知识',content='更新后的说明',anchoring={})]
        self.assertIsNone(read_models(self.documents,changed_knowledge,'profile'))
        data=json.loads(artifact_path(identity).read_text());data['payload_sha256']='invalid'
        artifact_path(identity).write_text(json.dumps(data))
        self.assertIsNone(read_models(self.documents,self.knowledge,'profile'))

    def test_unbound_quotes_are_never_prepared(self):
        self.insights['candidates']=[{'label':'EXP_TERMINOLOGY_BARRIER','evidence_quote':'伪造原文',
            'rationale':'合成理由','suggested_action':'核对原文','knowledge_refs':['K1']}]
        with self.assertRaisesRegex(ValueError,'QUOTE_INVALID'):self.prepare()
        self.assertIsNone(read_models(self.documents,self.knowledge,'profile'))

    def test_worker_reuses_only_preprocessing_and_still_generates_report(self):
        self.prepare();prepared=read_models(self.documents,self.knowledge,'profile')
        with patch('services.api.app.worker.OpenAiCompatibleExtractor') as extractor, \
             patch('services.api.app.worker.detect_semantic',side_effect=AssertionError('Preloaded')) as detector, \
             patch('services.api.app.worker.draft_report',return_value={'status':'completed','draft':{'sections':[],'actions':[]}}) as report, \
             patch('services.api.app.web_knowledge.supplement_knowledge',return_value=([],{})):
            result=analyze_models('合成材料原文。',[],None,{},[],{},lambda stage:None,
                                  defer_patient_analysis=True,preloaded_models=prepared)
        extractor.return_value.extract.assert_not_called();detector.assert_not_called();report.assert_called_once()
        self.assertEqual(result[-1]['material_preprocessing'],'preloaded')
        self.assertEqual(result[-1]['model_seconds']['extract_seconds'],0)
