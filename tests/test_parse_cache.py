import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4
from PIL import Image
from services.api.app.parse_cache import cacheable,cached_pages,payload_digest
from services.api.app.worker import parse_pdf,process_run,claim_run,route_document,OCR_VERSION,ROUTING_VERSION

def page(index=0):
    return {'page_index':index,'page_kind':'scanned','text':'【合成材料】医疗总费用120元。',
        'content_hash':'a'*64,'status':'parsed','requires_ocr':False,'requires_vision':False,
        'parser_version':'synthetic-ocr-v1','blocks':[{'type':'paragraph','order':0,
            'text':'【合成材料】医疗总费用120元。','bbox':[0,0,1,1],'metadata':{}}],
        'metadata':{'photo_quality':{'needs_reupload':False}}}

class ParseCacheTests(unittest.TestCase):
    def test_only_successful_clear_recognition_is_reused(self):
        self.assertTrue(cacheable(page()))
        for changes in ({'status':'failed'},{'status':'unreadable'},{'requires_ocr':True},{'text':''},
                        {'metadata':{'photo_quality':{'needs_reupload':True}}}):
            self.assertFalse(cacheable({**page(),**changes}))

    def test_corrupted_checkpoint_is_ignored_and_lookup_is_scoped_to_file_and_parser(self):
        document={'document_id':uuid4(),'document_version':2,'source_hash':'b'*64,'case_id':uuid4()}
        conn=MagicMock();good=page();bad={**page(1),'text':'corrupted'}
        conn.execute.return_value.fetchall.side_effect=[[
            {'page_index':0,'page_payload':good,'payload_sha256':payload_digest(good)},
            {'page_index':1,'page_payload':bad,'payload_sha256':payload_digest(page(1))}],[]]
        result=cached_pages(conn,document,'c'*64,{'synthetic-ocr-v1'},'router-v1','pipeline-v1')
        self.assertEqual(result,{0:good})
        self.assertEqual(conn.execute.call_args_list[0].args[1],
            (document['document_id'],2,'b'*64,'c'*64))
        self.assertIn(document['case_id'],conn.execute.call_args_list[1].args[1])

    def test_pdf_retry_calls_ocr_only_for_the_page_that_did_not_complete(self):
        ocr=MagicMock(version='synthetic-ocr-v1',method='synthetic')
        recognized={'text':'合成医疗材料','blocks':[{'type':'paragraph','order':0,'text':'合成医疗材料',
            'bbox':[0,0,1,1],'metadata':{'confidence_score':.99}}],'request_id':'synthetic','angle':0}
        ocr.recognize.side_effect=[recognized,RuntimeError('SYNTHETIC_OCR_FAILED')]
        reader=MagicMock(is_encrypted=False);reader.pages=[MagicMock(),MagicMock()]
        for item in reader.pages:item.extract_text.return_value=''
        rendered=MagicMock();rendered.__getitem__.return_value.render.return_value.to_pil.return_value=Image.new('RGB',(20,20),'white')
        saved={}
        def checkpoint(value):saved[value['page_index']]=copy.deepcopy(value)
        with patch('services.api.app.worker.PdfReader',return_value=reader), \
             patch('services.api.app.worker.page_image_count',return_value=1), \
             patch('services.api.app.worker.pdfium.PdfDocument',return_value=rendered):
            with self.assertRaisesRegex(RuntimeError,'SYNTHETIC_OCR_FAILED'):
                parse_pdf(Path('synthetic.pdf'),ocr,checkpoint=checkpoint)
            self.assertEqual(set(saved),{0})
            ocr.recognize.side_effect=[recognized]
            pages=parse_pdf(Path('synthetic.pdf'),ocr,cached=saved,checkpoint=checkpoint)
        self.assertEqual(ocr.recognize.call_count,3,'Two first-attempt calls plus only the failed page on retry')
        self.assertEqual(len(pages),2)


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'),'Isolated PostgreSQL not configured')
class ParseCheckpointDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from services.api.app.repository import connect
        cls.dsn=os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL'];cls.schema='parse_checkpoint_'+uuid4().hex
        with connect(cls.dsn) as conn:
            conn.prepare_threshold=None;conn.execute(f'CREATE SCHEMA {cls.schema}')
            conn.execute(f'SET search_path TO {cls.schema}')
            for migration in sorted((Path(__file__).resolve().parents[1]/'services/api/sql').glob('*.sql')):
                conn.execute(migration.read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        from services.api.app.repository import connect
        with connect(cls.dsn) as conn:conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def connection(self):
        from services.api.app.repository import connect
        conn=connect(self.dsn);conn.prepare_threshold=None;conn.autocommit=True
        conn.execute(f'SET search_path TO {self.schema}');return conn

    def test_report_failure_keeps_recognition_for_a_new_run_and_a_reopened_connection(self):
        from services.api.app import conversation_repository as chats
        from services.api.app.repository import token_digest,create_analysis_run
        from services.api.app.contracts.core import DocumentVersionRef
        actor,subject,consent,conversation,document=[uuid4() for _ in range(5)]
        with tempfile.TemporaryDirectory() as temporary:
            storage=Path(temporary).resolve();image_path=storage/'synthetic.png'
            Image.new('RGB',(20,20),'white').save(image_path)
            digest=hashlib.sha256(image_path.read_bytes()).hexdigest()
            with self.connection() as conn:
                conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s)',(actor,token_digest(uuid4().hex)))
                conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)',(actor,subject))
                conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'test',1)",(consent,subject))
                conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())",(consent,))
                current=chats.create_conversation(conn,actor,conversation,subject_id=subject)
                case=current['case_id']
                conn.execute('''INSERT INTO documents(document_id,case_id,media_type,byte_size,source_hash,source_ref,storage_ref,status,policy_version)
                    VALUES (%s,%s,'image/png',%s,%s,'synthetic.png',%s,'registered','test')''',
                    (document,case,image_path.stat().st_size,digest,str(image_path)))
                create_analysis_run(conn,actor_id=actor,case_id=case,document_versions=[DocumentVersionRef(document_id=document,document_version=1)],pipeline_version='document-parser-v1',force_new=False)
                run=claim_run(conn)
                ocr=MagicMock(version=OCR_VERSION,method='synthetic')
                ocr.recognize.return_value={'text':'合成材料120元','blocks':[{'type':'paragraph','order':0,'text':'合成材料120元','bbox':[0,0,1,1],
                    'metadata':{'confidence_score':.99}}],'request_id':'synthetic','angle':0}
                with patch('services.api.app.worker.create_ocr',return_value=ocr), \
                     patch('services.api.app.worker.analyze_models',side_effect=RuntimeError('SYNTHETIC_REPORT_FAILED')):
                    process_run(conn,run,storage)
                self.assertEqual(conn.execute('SELECT status FROM analysis_runs WHERE run_id=%s',(run['run_id'],)).fetchone()['status'],'failed')
                self.assertEqual(ocr.recognize.call_count,1)
                self.assertEqual(conn.execute('SELECT count(*) n FROM parsed_page_cache WHERE document_id=%s',(document,)).fetchone()['n'],1)
            with self.connection() as conn:
                create_analysis_run(conn,actor_id=actor,case_id=case,document_versions=[DocumentVersionRef(document_id=document,document_version=1)],pipeline_version='document-parser-v1',force_new=False)
                retry=claim_run(conn);self.assertNotEqual(retry['run_id'],run['run_id'])
                with patch('services.api.app.worker.create_ocr',side_effect=AssertionError('must reuse successful OCR')), \
                     patch('services.api.app.worker.route_document',wraps=route_document) as route, \
                     patch('services.api.app.worker.analyze_models',side_effect=RuntimeError('SYNTHETIC_REPORT_FAILED')) as model:
                    process_run(conn,retry,storage)
                self.assertEqual(set(route.call_args.kwargs['cached']),{0})
                self.assertEqual(model.call_count,1,'Recognition is reused but failed report generation is retried')
                self.assertEqual(conn.execute('SELECT status FROM analysis_runs WHERE run_id=%s',(retry['run_id'],)).fetchone()['status'],'failed')
                cached=conn.execute('SELECT * FROM parsed_page_cache WHERE document_id=%s',(document,)).fetchone()
                payload=cached['page_payload'];block=payload['blocks'][0]
                conn.execute('''INSERT INTO document_pages(document_id,document_version,page_index,text_content,
                    content_hash,parser_version,status,page_kind,routing_version,requires_ocr,requires_vision,structure_metadata)
                    VALUES (%s,1,0,%s,%s,%s,'parsed','scanned',%s,false,false,%s::jsonb)''',
                    (document,payload['text'],payload['content_hash'],OCR_VERSION,ROUTING_VERSION,json.dumps(payload['metadata'])))
                conn.execute('''INSERT INTO page_blocks(block_id,run_id,case_id,document_id,document_version,page_index,
                    block_type,reading_order,text_content,bbox,metadata,extraction_method,source_hash,parser_version)
                    VALUES (%s,%s,%s,%s,1,0,'paragraph',0,%s,%s::jsonb,%s::jsonb,'synthetic',%s,%s)''',
                    (uuid4(),run['run_id'],case,document,block['text'],json.dumps(block.get('bbox')),
                     json.dumps(block['metadata']),digest,OCR_VERSION))
                conn.execute('DELETE FROM parsed_page_cache WHERE document_id=%s',(document,))
                reference={'document_id':document,'document_version':1,'case_id':case,'source_hash':digest}
                self.assertEqual(cached_pages(conn,{**reference,'source_hash':'f'*64},cached['parser_fingerprint'],{OCR_VERSION},ROUTING_VERSION,'document-parser-v1'),{})
                self.assertEqual(cached_pages(conn,reference,cached['parser_fingerprint'],{'new-ocr-version'},ROUTING_VERSION,'document-parser-v1'),{})
                self.assertEqual(cached_pages(conn,reference,cached['parser_fingerprint'],{OCR_VERSION},ROUTING_VERSION,'different-pipeline'),{})
                create_analysis_run(conn,actor_id=actor,case_id=case,document_versions=[DocumentVersionRef(document_id=document,document_version=1)],pipeline_version='document-parser-v1',force_new=False)
                legacy_retry=claim_run(conn)
                with patch('services.api.app.worker.create_ocr',side_effect=AssertionError('must adopt pre-existing recognition')), \
                     patch('services.api.app.worker.analyze_models',side_effect=RuntimeError('SYNTHETIC_REPORT_FAILED')) as model:
                    process_run(conn,legacy_retry,storage)
                self.assertEqual(model.call_count,1,'Previously saved document_pages and blocks are reusable immediately')
                Image.new('RGB',(20,20),'black').save(image_path)
                create_analysis_run(conn,actor_id=actor,case_id=case,document_versions=[DocumentVersionRef(document_id=document,document_version=1)],pipeline_version='document-parser-v1',force_new=False)
                changed=claim_run(conn)
                with patch('services.api.app.worker.create_ocr') as factory:
                    process_run(conn,changed,storage)
                factory.assert_not_called()
                self.assertEqual(conn.execute('SELECT error FROM analysis_runs WHERE run_id=%s',(changed['run_id'],)).fetchone()['error']['code'],'SOURCE_HASH_MISMATCH')
