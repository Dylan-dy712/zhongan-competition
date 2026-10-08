"""Member contracts and isolated PostgreSQL HTTP checks (synthetic data only)."""
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from services.api.app import accounts
from services.api.app.main import app, database
from services.api.app.repository import connect


class MemberContractTests(unittest.TestCase):
    def test_validation_and_no_identity_injection(self):
        body = dict(name='  Synthetic member  ', relationship='parent')
        self.assertEqual(accounts.MemberInput(**body).name, 'Synthetic member')
        for changes in ({'name':'   '}, {'relationship':'unknown'}, {'gender':'unknown'},
                        {'birth_date':date.today()+timedelta(days=1)}, {'subject_id':str(uuid4())},
                        {'actor_id':str(uuid4())}, {'profile_completed':True}):
            with self.assertRaises(ValidationError):
                accounts.MemberInput(**{**body,**changes})


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'), 'Isolated PostgreSQL DSN not configured')
class FamilyDatabaseTests(unittest.TestCase):
    def test_member_isolation_migration_consent_and_record_ownership(self):
        dsn=os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL']
        schema='family_test_'+uuid4().hex
        def connection():
            conn=connect(dsn);conn.prepare_threshold=None
            conn.execute(f'SET search_path TO {schema}');conn.commit()
            return conn
        def isolated_database():
            with connection() as conn:yield conn
        with connect(dsn) as conn:
            conn.execute(f'CREATE SCHEMA {schema}')
        try:
            migrations=Path(__file__).resolve().parents[1]/'services/api/sql'
            with connection() as conn:
                for migration in sorted(migrations.glob('*.sql')):conn.execute(migration.read_text(encoding='utf-8'))
            app.dependency_overrides[database]=isolated_database
            with TestClient(app) as client:
                body=dict(username='13900000011',password='1',display_name='Synthetic owner',care_consent=True)
                response=client.post('/v1/auth/register',json=body)
                self.assertEqual(response.status_code,201,response.text)
                headers={'Authorization':'Bearer '+response.json()['access_token']}
                other=client.post('/v1/auth/register',json={**body,'username':'13900000012'}).json()
                outsider={'Authorization':'Bearer '+other['access_token']}
                # Migration backfills existing self without changing identity or consent.
                original=client.get('/v1/chat/subjects',headers=headers).json()[0]['subject_id']
                with connection() as conn:
                    conn.execute((migrations/'021_family_members.sql').read_text(encoding='utf-8'))
                    conn.execute((migrations/'021_family_members.sql').read_text(encoding='utf-8'))
                people=client.get('/v1/me/members',headers=headers).json()
                self.assertEqual(len(people),1);self.assertEqual(people[0]['subject_id'],original)
                self.assertFalse(people[0]['profile_completed'])
                self.assertEqual(client.post('/v1/me/members',headers=headers,json={'name':'Parent','relationship':'parent'}).status_code,409)
                path='/v1/me/members/'+original
                self.assertEqual(client.patch(path,headers=headers,json={'name':'Self','relationship':'self'}).status_code,200)
                family=client.post('/v1/me/members',headers=headers,json={'name':'Parent','relationship':'parent','birth_date':'1960-01-01'}).json()
                family_id=family['subject_id']
                self.assertNotEqual(family_id,original)
                self.assertEqual(client.get('/v1/me/members',headers=headers).json()[1]['name'],'Parent')
                self.assertEqual(client.patch(path,headers=headers,json={'name':'Self','relationship':'child'}).status_code,422)
                self.assertEqual(client.patch('/v1/me/members/'+family_id,headers=headers,json={'name':'Parent','relationship':'self'}).status_code,422)
                self.assertEqual(client.patch('/v1/me/members/'+family_id,headers=outsider,json={'name':'Wrong','relationship':'parent'}).status_code,404)
                consent_path='/v1/me/consents?subject_id='+family_id
                self.assertEqual(client.get(consent_path,headers=headers).json()['status'],'not_granted')
                self.assertEqual(client.get(consent_path,headers=outsider).status_code,404)
                own_conv=client.post('/v1/conversations',headers=headers,json={'conversation_id':str(uuid4()),'subject_id':original}).json()
                self.assertEqual(own_conv['subject_id'],original)
                denied=client.post('/v1/conversations',headers=headers,json={'conversation_id':str(uuid4()),'subject_id':family_id})
                self.assertEqual(denied.status_code,422)
                grant_headers={**headers,'Idempotency-Key':'family-grant'}
                grant_body={'confirmation':True,'expected_version':0}
                grant=client.post(consent_path,headers=grant_headers,json=grant_body)
                self.assertEqual(grant.status_code,200,grant.text)
                self.assertEqual(client.post(consent_path,headers=grant_headers,json=grant_body).json(),grant.json())
                self.assertEqual(client.post('/v1/me/consents?subject_id='+original,headers=grant_headers,json=grant_body).status_code,409)
                family_conv=client.post('/v1/conversations',headers=headers,json={'conversation_id':str(uuid4()),'subject_id':family_id}).json()
                self.assertEqual(family_conv['subject_id'],family_id)
                self.assertEqual(client.get('/v1/conversations?subject_id='+family_id,headers=headers).json(),[family_conv])
                self.assertEqual(client.get('/v1/conversations?subject_id='+family_id,headers=outsider).status_code,404)
                self.assertEqual(client.get('/v1/conversations/'+family_conv['conversation_id'],headers=outsider).status_code,404)
                revoked=client.post(consent_path,headers={**headers,'Idempotency-Key':'family-revoke'},json={'confirmation':False,'expected_version':1})
                self.assertEqual(revoked.status_code,200,revoked.text)
                self.assertEqual(client.get('/v1/conversations?subject_id='+family_id,headers=headers).json(),[])
                self.assertEqual(client.get('/v1/conversations/'+family_conv['conversation_id'],headers=headers).status_code,404)
                self.assertEqual(client.get('/v1/conversations?subject_id='+original,headers=headers).json(),[own_conv])
                self.assertEqual(len(client.get('/v1/me/members',headers=headers).json()),2)
                self.assertEqual(client.get('/v1/me/consents?subject_id='+original,headers=headers).json()['status'],'active')
        finally:
            app.dependency_overrides.pop(database,None)
            with connect(dsn) as conn:conn.execute(f'DROP SCHEMA {schema} CASCADE')


if __name__=='__main__':unittest.main()
