"""Allocator security, pool concurrency and real account access isolation."""
import importlib.util
import os
import secrets
import unittest
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


if __name__ == '__main__':
    unittest.main()
