import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4

import requests
from pypdf import PdfWriter
from services.api.app.judge_sample_cache import read_sample_pages,write_sample_pages,reviewed_document_pages
from services.api.app.worker import route_document,evidence_for_page
from services.api.app.analysis_review import source_verdict


def recognized():
    return {'page_index':0,'page_kind':'scanned','text':'合成材料，需门诊复诊。',
        'content_hash':'a'*64,'status':'parsed','requires_ocr':False,'requires_vision':False,
        'parser_version':'test-ocr','blocks':[{'type':'paragraph','order':0,'text':'合成材料，需门诊复诊。',
        'bbox':[0,0,1,1],'metadata':{'confidence_score':.99}}],
        'metadata':{'ocr_method':'synthetic','photo_quality':{'needs_reupload':False}}}


class ReviewedSampleCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name);self.assets=self.directory/'assets';self.assets.mkdir()
        self.path=self.assets/'synthetic.pdf'
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(self.path)
        self.item={'id':'synthetic','file':'synthetic.pdf','name':'合成材料.pdf','page_count':1,
            'media_type':'application/pdf','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}
        self.manifest={'sample_id':'synthetic-01','version':'test-v1','data_origin':'official_deidentified',
            'file_count':1,'page_count':1,'notice':'仅合成资料','documents':[self.item]}
        (self.assets/'manifest.json').write_text(json.dumps(self.manifest),encoding='utf-8')
        environment=patch.dict(os.environ,{'ZHONGAN_JUDGE_SAMPLE_ROOT':str(self.assets),
            'ZHONGAN_JUDGE_RECOGNITION_ROOT':str(self.directory/'cache')})
        environment.start();self.addCleanup(environment.stop)
        self.fingerprint='b'*64;self.versions={'test-ocr'}
        self.case={'created_by':uuid4(),'data_origin':'official_deidentified',
            'source_ref':'judge-upload-sample:synthetic-01','user_context':{'judge_demo':True,
            'sample_id':'synthetic-01','sample_version':'test-v1','notice':self.manifest['notice']}}
        self.document={'document_id':uuid4(),'document_version':1,'case_id':uuid4(),
            'media_type':'application/pdf','source_hash':self.item['sha256']}

    def connection(self,case=None,judge=True):
        conn=MagicMock();conn.execute.return_value.fetchone.side_effect=[case or self.case,{'name':'judge_demo_slots'},
            {'actor_id':self.case['created_by']} if judge else None]
        return conn

    def prepare(self,page=None):
        write_sample_pages(self.manifest,self.item,self.fingerprint,[page or recognized()],self.versions)

    def test_two_approved_uploads_reuse_recognition_without_reusing_evidence_ids(self):
        self.prepare()
        first=reviewed_document_pages(self.connection(),self.document,self.fingerprint,self.versions)
        second_document={**self.document,'document_id':uuid4(),'case_id':uuid4()}
        second=reviewed_document_pages(self.connection(),second_document,self.fingerprint,self.versions)
        with patch('services.api.app.worker.create_ocr',side_effect=AssertionError('Do not repeat OCR')):
            pages=route_document(self.document,self.path,'document-parser-v1',cached=first)
        self.assertEqual(pages,[recognized()]);self.assertEqual(first,second)
        a=evidence_for_page(self.document,pages[0]);b=evidence_for_page(second_document,second[0])
        self.assertNotEqual(a[0]['evidence_id'],b[0]['evidence_id'])
        self.assertNotEqual(a[0]['document_id'],b[0]['document_id'])

    def test_same_bytes_do_not_authorize_an_ordinary_or_forged_judge_case(self):
        self.prepare()
        ordinary={**self.case,'data_origin':'synthetic'}
        self.assertEqual(reviewed_document_pages(self.connection(ordinary),self.document,self.fingerprint,self.versions),{})
        self.assertEqual(reviewed_document_pages(self.connection(judge=False),self.document,self.fingerprint,self.versions),{})
        wrong={**self.document,'source_hash':'c'*64}
        self.assertEqual(reviewed_document_pages(self.connection(),wrong,self.fingerprint,self.versions),{})

    def test_parser_version_sample_bytes_and_cache_integrity_are_bound(self):
        self.prepare()
        self.assertEqual(read_sample_pages(self.manifest,self.item,'d'*64,self.versions),{})
        self.assertEqual(read_sample_pages(self.manifest,self.item,self.fingerprint,{'new-ocr'}),{})
        target=next((self.directory/'cache').glob('*.json'))
        target.write_text('[]',encoding='utf-8')
        self.assertEqual(read_sample_pages(self.manifest,self.item,self.fingerprint,self.versions),{})
        self.prepare()
        payload=json.loads(target.read_text(encoding='utf-8'));payload['pages'][0]['text']='被改动的结果'
        target.write_text(json.dumps(payload),encoding='utf-8')
        self.assertEqual(read_sample_pages(self.manifest,self.item,self.fingerprint,self.versions),{})
        self.prepare();self.path.write_bytes(self.path.read_bytes()+b'changed')
        self.assertEqual(reviewed_document_pages(self.connection(),self.document,self.fingerprint,self.versions),{})

    def test_low_confidence_blocks_remain_excluded_and_warnings_survive(self):
        page=recognized();page['blocks'].append({'type':'paragraph','order':1,'text':'不可靠金额999',
            'metadata':{'confidence_score':.2,'needs_clearer_photo':True}})
        page['metadata']['photo_quality']={'needs_reupload':True,'uncertain_lines':1}
        self.prepare(page)
        cached=read_sample_pages(self.manifest,self.item,self.fingerprint,self.versions)[0]
        self.assertTrue(cached['metadata']['photo_quality']['needs_reupload'])
        self.assertEqual([e['text'] for e in evidence_for_page(self.document,cached)],['合成材料，需门诊复诊。'])
        changed=copy.deepcopy(page);changed['text']+='\n不可靠金额999'
        self.assertEqual(write_sample_pages(self.manifest,self.item,self.fingerprint,[changed],self.versions),0)


class FidelityTransportTests(unittest.TestCase):
    def config(self):
        config=MagicMock();config.base_url='https://qianfan.baidubce.com/v2';config.model_id='glm-5.3-flash'
        return config

    def test_timeout_retries_same_review_with_remaining_budget(self):
        config=self.config();config._call.side_effect=[requests.ReadTimeout(),({},'{"accepted":true,"issues":[]}')]
        with patch('services.api.app.analysis_review.time.monotonic',side_effect=[0,0,26]):
            verdict,_=source_verdict(config,[{'role':'user','content':'合成资料'}])
        self.assertTrue(verdict.accepted);self.assertEqual(config._call.call_count,2)
        self.assertEqual(config._call.call_args_list[0].kwargs['timeout'],(10,25))
        self.assertEqual(config._call.call_args_list[1].kwargs['timeout'],(10,9))
        self.assertEqual(config._call.call_args_list[0].args,config._call.call_args_list[1].args)

    def test_two_transport_failures_never_approve_or_expand_request_count(self):
        config=self.config();config._call.side_effect=requests.ReadTimeout()
        with self.assertRaises(requests.ReadTimeout):source_verdict(config,[])
        self.assertEqual(config._call.call_count,2)

    def test_invalid_response_and_permanent_http_error_are_not_transport_retried(self):
        config=self.config();config._call.return_value=({},'{"accepted":true,"issues":[{}]}')
        with self.assertRaises(ValueError):source_verdict(config,[])
        self.assertEqual(config._call.call_count,1)
        config=self.config();config._call.side_effect=requests.HTTPError()
        with self.assertRaises(requests.HTTPError):source_verdict(config,[])
        self.assertEqual(config._call.call_count,1)
