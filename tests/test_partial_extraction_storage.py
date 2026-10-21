"""Native PostgreSQL upgrade coverage for partially extracted document fields."""
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4
import psycopg
from psycopg import sql

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'),'Native PostgreSQL DSN not configured')
class PartialExtractionStorageTests(unittest.TestCase):
    def test_upgrade_persists_partial_provenance_and_still_rejects_unknown_states(self):
        schema='partial_extraction_test_'+uuid4().hex
        with psycopg.connect(os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL']) as conn:
            try:
                conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
                conn.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
                conn.execute('CREATE TABLE cases(case_id uuid PRIMARY KEY)')
                conn.execute('CREATE TABLE analysis_runs(run_id uuid PRIMARY KEY)')
                conn.execute((ROOT/'services/api/sql/006_model_extractions.sql').read_text(encoding='utf8'))
                case,run=uuid4(),uuid4()
                conn.execute('INSERT INTO cases VALUES (%s)',(case,));conn.execute('INSERT INTO analysis_runs VALUES (%s)',(run,))
                def insert(status):
                    return conn.execute('''INSERT INTO model_extractions(extraction_id,run_id,case_id,provider,model_id,
                        prompt_version,schema_version,status,candidates,usage_metadata)
                        VALUES (%s,%s,%s,'synthetic','synthetic',%s,'synthetic',%s,%s::jsonb,%s::jsonb) RETURNING status,candidates,usage_metadata''',
                        (uuid4(),run,case,uuid4().hex,status,json.dumps({'candidates':[]}),
                         json.dumps({'strategy':'C','failed_pages':0,'requires_review':True})))
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with conn.transaction():insert('partial')
                migration=(ROOT/'services/api/sql/030_partial_model_extractions.sql').read_text(encoding='utf8')
                conn.execute(migration);conn.execute(migration)
                status,candidates,metadata=insert('partial').fetchone()
                self.assertEqual(status,'partial');self.assertEqual(candidates,{'candidates':[]})
                self.assertTrue(metadata['requires_review'])
                for status in ['completed','invalid','failed','not_configured']:insert(status)
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with conn.transaction():insert('invented_success')
            finally:
                conn.rollback()  # Entire isolated schema and synthetic rows disappear.
