"""Allocator security, pool concurrency and real account access isolation."""
import importlib.util
import os
import secrets
import unittest
import json
import hashlib
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from pydantic import ValidationError

from services.api.app import accounts
from services.api.app.main import app as care_app, database
from services.api.app.repository import actor_for_token

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('judge_allocator', ROOT / 'services/judge_demo/app.py')
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


class EntryContractTests(unittest.TestCase):
    def test_invitation_and_visitor_validation_fail_before_connecting(self):
        with patch.dict(os.environ, {'ZHONGAN_JUDGE_ENTRY_KEY': 'test-entry-' + 'x' * 40}):
            with patch.object(judge.psycopg, 'connect') as connect:
                for authorization in (None, 'Demo wrong-key', 'Bearer test-entry-' + 'x' * 40):
                    with self.assertRaises(HTTPException) as error:
                        judge.judge_session(judge.Visitor(visitor_id='a' * 64), judge.Response(), authorization)
                    self.assertEqual(error.exception.status_code, 403)
                for body in ({'visitor_id': 'short'}, {'visitor_id': 'a' * 64, 'actor_id': str(uuid4())}):
                    with self.assertRaises(ValidationError):
                        judge.Visitor(**body)
                connect.assert_not_called()
        with patch.dict(os.environ, {'ZHONGAN_JUDGE_ENTRY_KEY': ''}):
            with self.assertRaises(HTTPException) as error:
                judge.validate_entry(None)
            self.assertEqual(error.exception.status_code, 503)

    def test_entry_has_no_credentials_and_prevents_caching_and_embedding(self):
        response = judge.entry()
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertNotIn('password', Path(response.path).read_text(encoding='utf-8'))
        self.assertTrue(Path(judge.entry_script().path).is_file())

    def test_library_rejects_missing_assets_and_path_escape(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder,patch.dict(os.environ,{'ZHONGAN_JUDGE_SAMPLE_ROOT':folder}):
            with self.assertRaises(HTTPException) as error:judge.sample_manifest()
            self.assertEqual(error.exception.status_code,503)
            manifest={'sample_id':'test','version':'v1','data_origin':'official_deidentified','file_count':1,'page_count':1,
                      'documents':[{'id':'test','file':'../escaped.pdf'}]}
            Path(folder,'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(HTTPException) as error:judge.sample_manifest()
            self.assertEqual(error.exception.status_code,503)


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'), 'Native PostgreSQL DSN not configured')
class NativeJudgePoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL']
        cls.schema = 'judge_test_' + uuid4().hex
        migrations = Path(os.getenv('ZHONGAN_TEST_MIGRATIONS_DIR', ROOT / 'services/api/sql'))
        with psycopg.connect(cls.dsn, row_factory=dict_row) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
            conn.execute(f'SET search_path TO {cls.schema}')
            for path in sorted(migrations.glob('*.sql')):
                conn.execute(path.read_text(encoding='utf-8'))
            judge.seed_pool(conn)

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def connection(self):
        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        conn.execute(f'SET search_path TO {self.schema}')
        conn.commit()
        return conn

    def test_fifty_concurrent_visitors_repeat_scan_capacity_and_access_isolation(self):
        visitors = [secrets.token_hex(32) for _ in range(50)]
        def visit(visitor):
            with self.connection() as conn:
                return judge.allocate(conn, visitor)
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(visit, visitors))
        self.assertEqual(len({result['slot'] for result in results}), 50)
        self.assertEqual(len({result['user']['username'] for result in results}), 50)
        self.assertEqual(len({result['access_token'] for result in results}), 50)
        with self.assertRaises(HTTPException) as error:
            visit(secrets.token_hex(32))
        self.assertEqual(error.exception.status_code, 409)
        with ThreadPoolExecutor(max_workers=8) as executor:
            repeat = list(executor.map(visit, [visitors[0]] * 8))
        self.assertTrue(all(item['slot'] == results[0]['slot'] for item in repeat))
        with self.connection() as conn:
            judge.seed_pool(conn)
            counts = conn.execute('SELECT count(*) AS total,count(visitor_sha256) AS assigned FROM judge_demo_slots').fetchone()
            self.assertEqual(counts, {'total': 50, 'assigned': 50})
            actors = [actor_for_token(conn, item['access_token']) for item in results]
            self.assertEqual(len(set(actors)), 50)
            subjects = [accounts.list_members(conn, actor)[0] for actor in actors]
            self.assertEqual(len({person['subject_id'] for person in subjects}), 50)
            self.assertTrue(all(person['profile_completed'] for person in subjects))
            with self.assertRaises(HTTPException):
                accounts.member_scope(conn, actors[0], subjects[1]['subject_id'])
        def isolated_database():
            with self.connection() as conn:
                yield conn
        care_app.dependency_overrides[database] = isolated_database
        try:
            with TestClient(care_app) as client:
                first_headers = {'Authorization': 'Bearer ' + results[0]['access_token']}
                second_headers = {'Authorization': 'Bearer ' + results[1]['access_token']}
                conversation = client.post('/v1/conversations', headers=first_headers, json={
                    'conversation_id': str(uuid4()), 'subject_id': str(subjects[0]['subject_id']), 'recall_enabled': False})
                self.assertIn(conversation.status_code, (200,201), conversation.text)
                path = '/v1/conversations/' + conversation.json()['conversation_id']
                self.assertEqual(client.get(path, headers=first_headers).status_code, 200)
                self.assertEqual(client.get(path, headers=second_headers).status_code, 404)
                self.assertEqual(client.post('/v1/auth/logout', headers=first_headers).status_code, 204)
                self.assertEqual(client.get('/v1/auth/me', headers=first_headers).status_code, 401)
                self.assertEqual(client.get('/v1/auth/me', headers=second_headers).status_code, 200)
                # Repeat scan remains the same account even after that tab logs out.
                self.assertEqual(visit(visitors[0])['slot'], results[0]['slot'])
                with self.connection() as conn:
                    conn.execute("UPDATE auth_sessions SET expires_at=now()-interval '1 second'")
                self.assertEqual(client.get('/v1/auth/me', headers=second_headers).status_code, 401)
        finally:
            care_app.dependency_overrides.pop(database, None)


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'),'Native PostgreSQL DSN not configured')
class NativeJudgeLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pypdf import PdfWriter
        cls.dsn=os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL'];cls.schema='judge_library_test_'+uuid4().hex
        cls.original_connect=staticmethod(psycopg.connect)
        cls.temporary=tempfile.TemporaryDirectory(dir=ROOT);cls.directory=Path(cls.temporary.name)
        cls.assets=cls.directory/'assets';cls.assets.mkdir();cls.storage=cls.directory/'uploads';cls.storage.mkdir()
        documents=[]
        for index in range(3):
            name=f'synthetic-{index}.pdf';path=cls.assets/name
            writer=PdfWriter();writer.add_blank_page(width=300+index,height=400);writer.write(path)
            documents.append({'id':f'synthetic-{index}','file':name,'name':name,'document_type':'出院记录' if index==0 else '费用清单',
                              'media_type':'application/pdf','page_count':1,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        cls.manifest={'sample_id':'synthetic-01','version':'test-v1','data_origin':'official_deidentified','title':'合成路径测试','summary':'测试',
                      'notice':'合成测试，非患者资料','file_count':3,'page_count':3,'claim_info':{},'documents':documents}
        (cls.assets/'manifest.json').write_text(json.dumps(cls.manifest),encoding='utf-8')
        cls.environment=patch.dict(os.environ,{'ZHONGAN_JUDGE_SAMPLE_ROOT':str(cls.assets)})
        cls.environment.__enter__()
        with cls.original_connect(cls.dsn,row_factory=dict_row) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}');conn.execute(f'SET search_path TO {cls.schema}')
            migrations=Path(os.getenv('ZHONGAN_TEST_MIGRATIONS_DIR',ROOT/'services/api/sql'))
            for path in sorted(migrations.glob('*.sql')):conn.execute(path.read_text(encoding='utf-8'))
            judge.seed_pool(conn)
            cls.actors=[row['actor_id'] for row in conn.execute('SELECT actor_id FROM judge_demo_slots ORDER BY slot LIMIT 2').fetchall()]
            cls.tokens=[accounts.session(conn,actor)['access_token'] for actor in cls.actors]
            cls.ordinary=accounts.register(conn,accounts.Registration(username='13900000003',password='synthetic-only',display_name='合成普通用户',care_consent=True))['access_token']

    @classmethod
    def tearDownClass(cls):
        cls.environment.__exit__(None,None,None)
        with cls.original_connect(cls.dsn) as conn:conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')
        cls.temporary.cleanup()

    def connection(self):
        conn=self.original_connect(self.dsn,row_factory=dict_row)
        conn.execute(f'SET search_path TO {self.schema}');conn.commit();return conn

    def test_private_download_then_real_upload_then_explicit_analysis(self):
        from services.api.app.main import document_storage_root
        first={'Authorization':'Bearer '+self.tokens[0]};second={'Authorization':'Bearer '+self.tokens[1]}
        with patch.object(judge.psycopg,'connect',side_effect=lambda *args,**kwargs:self.connection()),TestClient(judge.app) as library:
            self.assertEqual(library.get('/judge/sample').status_code,401)
            self.assertEqual(library.get('/judge/sample',headers={'Authorization':'Bearer '+self.ordinary}).status_code,403)
            self.assertEqual(library.get('/judge/sample/files/synthetic-0').status_code,401)
            meta=library.get('/judge/sample',headers=first)
            self.assertEqual(meta.status_code,200,meta.text);self.assertEqual(meta.json()['file_count'],3)
            self.assertNotIn('file',meta.json()['documents'][0]);self.assertNotIn('actor_id',meta.text)
            selected=[]
            for item in self.manifest['documents']:
                response=library.get('/judge/sample/files/'+item['id'],headers=first)
                self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store')
                self.assertEqual(hashlib.sha256(response.content).hexdigest(),item['sha256'])
                selected.append(response.content)
        with self.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM cases').fetchone()['n'],0,'Selecting sample files must never import a case')
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM documents').fetchone()['n'],0)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'],0)
            consent=accounts.care_consent(conn,self.actors[0])
        # Updating the reviewed library must preserve files already selected by a judge.
        previous=self.directory/'synthetic-01-test-v1'
        shutil.copytree(self.assets,previous)
        updated=json.loads(json.dumps(self.manifest));updated['version']='test-v2';updated['sample_id']='synthetic-02'
        first_asset=self.assets/updated['documents'][0]['file']
        newer_data=first_asset.read_bytes()+b'\n% reviewed compression revision\n'
        first_asset.write_bytes(newer_data)
        updated['documents'][0]['sha256']=hashlib.sha256(newer_data).hexdigest()
        (self.assets/'manifest.json').write_text(json.dumps(updated),encoding='utf-8')
        with patch.object(judge.psycopg,'connect',side_effect=lambda *args,**kwargs:self.connection()),TestClient(judge.app) as library:
            self.assertEqual(library.get('/judge/sample',headers=first).json()['version'],'test-v2')
            old=library.get('/judge/sample/files/synthetic-0?version=test-v1&sample_id=synthetic-01',headers=first)
            self.assertEqual(old.content,selected[0])
            self.assertEqual(library.get('/judge/sample/files/synthetic-0?version=../test-v1',headers=first).status_code,404)
            self.assertEqual(library.get('/judge/sample/files/synthetic-0?sample_id=../synthetic-01',headers=first).status_code,404)
        def isolated_database():
            with self.connection() as conn:yield conn
        care_app.dependency_overrides[database]=isolated_database
        care_app.dependency_overrides[document_storage_root]=lambda:self.storage
        try:
            with TestClient(care_app) as client:
                created=client.post('/v1/cases',headers={**first,'Idempotency-Key':'synthetic-sample-upload'},json={
                    'subject_id':str(consent['subject_id']),'consent_id':str(consent['consent_id']),
                    'source_ref':'judge-upload-sample:synthetic-01','data_origin':'official_deidentified','user_context':{
                        'judge_demo':True,'sample_id':'synthetic-01','sample_version':'test-v1','notice':self.manifest['notice']}})
                self.assertEqual(created.status_code,201,created.text)
                case=created.json()['case_id'];conversation=str(uuid4())
                response=client.post('/v1/conversations',headers=first,json={'conversation_id':conversation,'case_id':case,'recall_enabled':False})
                self.assertIn(response.status_code,(200,201),response.text)
                unrelated=client.post(f'/v1/conversations/{conversation}/documents',headers=first,files={'file':('synthetic-unapproved.pdf',b'%PDF-1.4\nNot in reviewed sample','application/pdf')})
                self.assertEqual(unrelated.status_code,422,'Unreviewed files must not be tagged as approved official samples')
                wrong_version=client.post(f'/v1/conversations/{conversation}/documents',headers=first,files={'file':('synthetic-0.pdf',newer_data,'application/pdf')})
                self.assertEqual(wrong_version.status_code,422,'Uploads must match the version actually selected')
                document_ids=[]
                for item,data in zip(self.manifest['documents'],selected):
                    uploaded=client.post(f'/v1/conversations/{conversation}/documents',headers=first,files={'file':(item['name'],data,'application/pdf')})
                    self.assertEqual(uploaded.status_code,201,uploaded.text);document_ids.append(uploaded.json()['document_id'])
                with self.connection() as conn:
                    self.assertEqual(conn.execute('SELECT count(*) AS n FROM documents').fetchone()['n'],3)
                    self.assertEqual(conn.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'],0,'Upload confirmation must precede analysis')
                body={'request_id':str(uuid4()),'message':'合成测试：开始分析已上传资料','document_ids':document_ids}
                started=client.post(f'/v1/conversations/{conversation}/analyses',headers=first,json=body)
                self.assertEqual(started.status_code,200,started.text)
                self.assertEqual(client.post(f'/v1/conversations/{conversation}/analyses',headers=first,json=body).status_code,200)
                with self.connection() as conn:self.assertEqual(conn.execute('SELECT count(*) AS n FROM analysis_runs').fetchone()['n'],1)
                path=f'/v1/cases/{case}/documents/{document_ids[0]}/content'
                self.assertEqual(client.get(path,headers=first).status_code,200)
                self.assertEqual(client.get(path,headers=second).status_code,404)
        finally:
            care_app.dependency_overrides.pop(database,None);care_app.dependency_overrides.pop(document_storage_root,None)
        with self.connection() as conn:
            current=accounts.care_consent(conn,self.actors[0])
            accounts.change_consent(conn,self.actors[0],accounts.ConsentChange(confirmation=False,expected_version=current['version']),'revoke-sample-download')
        with patch.object(judge.psycopg,'connect',side_effect=lambda *args,**kwargs:self.connection()),TestClient(judge.app) as library:
            self.assertEqual(library.get('/judge/sample/files/synthetic-0',headers=first).status_code,403)


if __name__ == '__main__':unittest.main()
