"""Isolated SQL/HTTP replacement check. Use a disposable PostgreSQL/PGlite DSN.

No OCR/model calls; synthetic UTF-8 files only. PGlite is not a concurrency test.
"""
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg import sql

from services.api.app import main as api
from services.api.app.conversation_agent import CareTools
from services.api.app.contracts.core import DocumentVersionRef
from services.api.app.repository import AccessDenied, connect, create_analysis_run, token_digest


def main():
    dsn = os.environ['ZHONGAN_REPLACEMENT_TEST_DATABASE_URL']
    schema = 'replacement_test_' + uuid4().hex
    admin = connect(dsn)
    admin.autocommit = True
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

    def connection():
        conn = connect(dsn)
        conn.prepare_threshold = None
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        conn.commit()
        return conn

    def database():
        with connection() as conn:
            yield conn

    try:
        actor, subject, consent = [uuid4() for _ in range(3)]
        token = uuid4().hex
        with connection() as conn:
            for migration in sorted(Path('services/api/sql').glob('*.sql')):
                conn.execute(migration.read_text(encoding='utf-8'))
            conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s)', (actor, token_digest(token)))
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)', (actor, subject))
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'synthetic',1)", (consent, subject))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())", (consent,))
        with tempfile.TemporaryDirectory() as storage:
            api.app.dependency_overrides[api.database] = database
            api.app.dependency_overrides[api.document_storage_root] = lambda: Path(storage)
            with TestClient(api.app) as client:
                headers = {'Authorization': 'Bearer ' + token}
                conversation_id = uuid4()
                created = client.post('/v1/conversations', headers=headers, json={'conversation_id': str(conversation_id), 'subject_id': str(subject)})
                assert created.status_code == 201, created.text
                case_id = UUID(created.json()['case_id'])
                base = f'/v1/conversations/{conversation_id}/documents'

                def upload(url, body):
                    return client.post(url, headers=headers, files={'file': ('synthetic.txt', body, 'text/plain')})

                old = upload(base, b'SYNTHETIC ORIGINAL')
                assert old.status_code == 201, old.text
                old_id = old.json()['document_id']
                replacement_url = f'{base}/{old_id}/replacement'
                new = upload(replacement_url, b'SYNTHETIC CLEAR REPLACEMENT')
                assert new.status_code == 201, new.text
                new_id = new.json()['document_id']
                retry = upload(replacement_url, b'SYNTHETIC CLEAR REPLACEMENT')
                assert retry.status_code == 200 and retry.json()['document_id'] == new_id, retry.text
                assert upload(replacement_url, b'DIFFERENT RETRY').status_code == 409
                assert upload(base, b'SYNTHETIC ORIGINAL').status_code == 409
                assert upload(f'{base}/{uuid4()}/replacement', b'UNKNOWN TARGET').status_code == 404
                original = client.get(f'/v1/cases/{case_id}/documents/{old_id}/content', headers=headers)
                assert original.status_code == 200 and original.content == b'SYNTHETIC ORIGINAL'
                with connection() as conn:
                    assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n'] == 2
                    assert conn.execute('SELECT count(*) n FROM document_replacements').fetchone()['n'] == 1
                    materials = CareTools(conn, actor, conversation_id).execute('list_materials', '{}')
                    assert old_id not in str(materials) and new_id in str(materials), materials
                    started = CareTools(conn, actor, conversation_id).execute('start_analysis', '{}')
                    run = conn.execute('SELECT document_versions FROM analysis_runs WHERE run_id=%s',
                                       (started['run_id'],)).fetchone()
                    assert [d['document_id'] for d in run['document_versions']] == [new_id], run
                    try:
                        create_analysis_run(conn, actor_id=actor, case_id=case_id,
                            document_versions=[DocumentVersionRef(document_id=old_id, document_version=1)],
                            pipeline_version='synthetic-test', force_new=False)
                    except AccessDenied:
                        pass
                    else:
                        raise AssertionError('Superseded document entered a new run')
                last = upload(f'{base}/{new_id}/replacement', b'SYNTHETIC SECOND REPLACEMENT')
                assert last.status_code == 201, last.text
                assert upload(replacement_url, b'SYNTHETIC CLEAR REPLACEMENT').status_code == 409
            print('PASS: migrations, HTTP replacement, retry deduplication, stale rejection, original preservation, active material selection, superseded-run rejection, replacement chain')
    finally:
        api.app.dependency_overrides.pop(api.database, None)
        api.app.dependency_overrides.pop(api.document_storage_root, None)
        admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


if __name__ == '__main__':
    main()
