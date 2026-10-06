"""Account contract/security tests, plus opt-in isolated native PostgreSQL checks."""
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.app import accounts
from services.api.app.main import app, database, current_actor, login_account, schema_error
from services.api.app.repository import actor_for_token, connect


class PasswordTests(unittest.TestCase):
    def test_random_salts_and_wrong_password(self):
        first=accounts.hash_password('synthetic-test-password')
        second=accounts.hash_password('synthetic-test-password')
        self.assertNotEqual(first,second)
        self.assertTrue(accounts.verify_password('synthetic-test-password',first))
        self.assertFalse(accounts.verify_password('different-password',first))
        self.assertFalse(accounts.verify_password('synthetic-test-password','broken'))

    def test_registration_cannot_select_identity_or_role(self):
        base=dict(username='Example_User',password='synthetic-test-password',display_name='合成账号',care_consent=False)
        self.assertEqual(accounts.Registration(**base).username,'example_user')
        for extra in ('actor_id','subject_id','role'):
            with self.assertRaises(ValidationError):accounts.Registration(**base,**{extra:str(uuid4())})
        with self.assertRaises(ValidationError):accounts.Registration(**{**base,'display_name':'   '})
        with self.assertRaises(ValidationError):accounts.Credentials(username='abc',password='short')

    def test_http_contract_rejects_invalid_payload_and_does_not_echo_password(self):
        async def stub_database():return object()
        app.dependency_overrides[database]=stub_database
        try:
            from fastapi import HTTPException,Request,Response
            from fastapi.exceptions import RequestValidationError
            handler=schema_error(Request({'type':'http'}),RequestValidationError([{'input':'short'}]))
            try:handler.send(None)
            except StopIteration as result:response=result.value
            self.assertEqual(response.status_code,422)
            self.assertNotIn(b'short',response.body)
            self.assertIn('/v1/auth/register',app.openapi()['paths'])
            with self.assertRaises(HTTPException) as error:current_actor(None,object())
            self.assertEqual(error.exception.status_code,401)
            with patch.object(accounts,'rate_limit'),patch.object(accounts,'login',side_effect=HTTPException(401,'用户名或密码不正确。')):
                with self.assertRaises(HTTPException) as error:
                    login_account(accounts.Credentials(username='abc',password='synthetic-test-password'),Request({'type':'http','client':('127.0.0.1',80)}),Response(),object())
                self.assertEqual(error.exception.status_code,401)
        finally:app.dependency_overrides.pop(database,None)


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'),'Native PostgreSQL test DSN not configured')
class NativeAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn=os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL']
        cls.schema='auth_test_'+uuid4().hex
        with connect(cls.dsn) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
            conn.execute(f'SET search_path TO {cls.schema}')
            root=Path(__file__).resolve().parents[1]/'services/api/sql'
            for migration in sorted(root.glob('*.sql')):conn.execute(migration.read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        with connect(cls.dsn) as conn:conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def test_accounts_consent_isolation_and_session_lifecycle(self):
        def isolated_database():
            with connect(self.dsn) as conn:
                conn.execute(f'SET search_path TO {self.schema}')
                conn.commit()
                yield conn
        app.dependency_overrides[database]=isolated_database
        try:
            with TestClient(app) as client:
                body={'username':'alpha','password':'synthetic-test-password','display_name':'合成A','care_consent':False}
                created=client.post('/v1/auth/register',json=body)
                self.assertEqual(created.status_code,201,created.text)
                token=created.json()['access_token'];headers={'Authorization':'Bearer '+token,'Idempotency-Key':'grant-one'}
                self.assertEqual(client.get('/v1/chat/subjects',headers=headers).json(),[])
                self.assertEqual(client.post('/v1/auth/register',json={**body,'username':'ALPHA'}).status_code,409)
                grant=client.post('/v1/me/consents',headers=headers,json={'confirmation':True,'expected_version':0})
                self.assertEqual(grant.status_code,200,grant.text)
                self.assertEqual(client.post('/v1/me/consents',headers=headers,json={'confirmation':True,'expected_version':0}).json()['version'],1)
                self.assertEqual(client.post('/v1/me/consents',headers=headers,json={'confirmation':False,'expected_version':0}).status_code,409)
                self.assertEqual(client.post('/v1/me/consents',headers={**headers,'Idempotency-Key':'stale-new-key'},json={'confirmation':True,'expected_version':0}).status_code,409)
                first_subject=client.get('/v1/chat/subjects',headers=headers).json()[0]['subject_id']
                conversation=client.post('/v1/conversations',headers=headers,json={'conversation_id':str(uuid4()),'subject_id':first_subject,'recall_enabled':False})
                self.assertIn(conversation.status_code,(200,201),conversation.text)
                other=client.post('/v1/auth/register',json={**body,'username':'beta','care_consent':True}).json()['access_token']
                other_headers={'Authorization':'Bearer '+other}
                self.assertNotEqual(first_subject,client.get('/v1/chat/subjects',headers=other_headers).json()[0]['subject_id'])
                denied=client.get('/v1/conversations/'+conversation.json()['conversation_id'],headers=other_headers)
                self.assertEqual(denied.status_code,404)
                self.assertEqual(client.post('/v1/me/consents',headers={**headers,'Idempotency-Key':'revoke-one'},json={'confirmation':False,'expected_version':1}).status_code,200)
                self.assertEqual(client.get('/v1/chat/subjects',headers=headers).json(),[])
                self.assertEqual(client.get('/v1/conversations/'+conversation.json()['conversation_id'],headers=headers).status_code,404)
                self.assertEqual(client.post('/v1/auth/login',json={**{k:body[k] for k in ('username','password')},'password':'wrong-password'}).status_code,401)
                signed=client.post('/v1/auth/login',json={k:body[k] for k in ('username','password')})
                self.assertEqual(signed.status_code,200,signed.text)
                self.assertEqual(client.post('/v1/auth/logout',headers=headers).status_code,204)
                self.assertEqual(client.get('/v1/auth/me',headers=headers).status_code,401)
                with connect(self.dsn) as conn:
                    conn.execute(f'SET search_path TO {self.schema}')
                    conn.execute("UPDATE auth_sessions SET expires_at=now()-interval '1 second'")
                self.assertEqual(client.get('/v1/auth/me',headers={'Authorization':'Bearer '+signed.json()['access_token']}).status_code,401)
        finally:app.dependency_overrides.pop(database,None)


if __name__=='__main__':unittest.main()
