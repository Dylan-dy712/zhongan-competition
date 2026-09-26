"""Local-only UI QA fixture. No mock model, no external model configuration.

Run alongside tools/chat-test-db. The two seeded turns are explicitly labelled
UI fixtures. New messages use the actual error path when the model is absent.
"""
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn
from psycopg import sql

from services.api.app import main as api
from services.api.app import conversation_repository as chats
from services.api.app.repository import connect, token_digest


def main():
    dsn='host=127.0.0.1 port=55439 dbname=postgres user=postgres sslmode=disable connect_timeout=5'
    schema='chat_ui_'+uuid4().hex
    with connect(dsn) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))

    def connection():
        conn=connect(dsn)
        conn.prepare_threshold=None
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        conn.commit()
        return conn

    def database():
        with connection() as conn:
            yield conn

    try:
        with connection() as conn:
            for migration in sorted(Path('services/api/sql').glob('*.sql')):
                conn.execute(migration.read_text(encoding='utf-8'))
            actor,subject,consent,conversation=[uuid4() for _ in range(4)]
            conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s)',(actor,token_digest('synthetic-ui-only')))
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)',(actor,subject))
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'ui-fixture',1)",(consent,subject))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())",(consent,))
            chats.create_conversation(conn,actor,conversation,subject_id=subject)
            turn=chats.begin_turn(conn,actor,conversation,uuid4(),'【界面测试】我想先了解费用。',[])
            chats.finish_turn(conn,actor,conversation,turn,answer={'text':'【界面测试数据，非模型回答】可以上传票据；如果材料没有费用明细，需要补充后再核对。','evidence_refs':[],'history_refs':[]})
            conn.execute("UPDATE conversations SET title='界面验收 · 合成样例' WHERE conversation_id=%s",(conversation,))
        for name in ('LLM_API_KEY','LLM_BASE_URL','LLM_MODEL_ID'):
            os.environ.pop(name,None)
        with tempfile.TemporaryDirectory(prefix='zhongan-chat-ui-') as storage:
            api.app.dependency_overrides[api.database]=database
            api.app.dependency_overrides[api.document_storage_root]=lambda:Path(storage)
            print('LOCAL UI FIXTURE: token=synthetic-ui-only; model intentionally unconfigured',flush=True)
            uvicorn.run(api.app,host='127.0.0.1',port=8000,log_level='warning')
    finally:
        api.app.dependency_overrides.clear()
        with connect(dsn) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__=='__main__':
    main()
