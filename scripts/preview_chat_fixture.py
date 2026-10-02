"""Local-only UI QA fixture. No mock model, no external model configuration.

Run alongside tools/chat-test-db. The two seeded turns are explicitly labelled
UI fixtures. New messages use the actual error path when the model is absent.
"""
import os
import json
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn
from psycopg import sql

from services.api.app import main as api
from services.api.app import conversation_repository as chats
from services.api.app.repository import connect, token_digest
from services.api.app.report_builder import SECTION_TYPES


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
            case=chats.create_conversation(conn,actor,conversation,subject_id=subject)['case_id']
            turn=chats.begin_turn(conn,actor,conversation,uuid4(),'【界面测试】我想先了解费用。',[])
            chats.finish_turn(conn,actor,conversation,turn,answer={'text':'【界面测试数据，非模型回答】可以上传票据；如果材料没有费用明细，需要补充后再核对。','evidence_refs':[],'history_refs':[]})
            conn.execute("UPDATE conversations SET title='界面验收 · 合成样例' WHERE conversation_id=%s",(conversation,))
            # Explicit UI state fixture, not a model output or release-gate evaluation.
            document,run,report,release=[uuid4() for _ in range(4)]
            conn.execute("""INSERT INTO documents(document_id,case_id,media_type,byte_size,source_hash,
                source_ref,storage_ref,status,policy_version) VALUES (%s,%s,'text/plain',1,%s,
                'synthetic-ui','synthetic-ui-no-file','parsed','synthetic-ui')""",(document,case,'b'*64))
            conn.execute("""INSERT INTO analysis_runs(run_id,case_id,input_hash,schema_version,pipeline_version,
                document_versions,status,current_stage,execution_mode) VALUES (%s,%s,%s,'0.1.0','synthetic-ui',
                %s::jsonb,'completed','validate','mock')""",(run,case,'c'*64,
                json.dumps([{'document_id':str(document),'document_version':1,'source_hash':'b'*64}])))
            sections=[{'section_type':kind,'claims':[{'claim_id':str(uuid4()),'claim_type':'to_confirm',
                'text':'【界面测试，非医学报告】此段仅用于验证页面展示、已读回执和反馈按钮。',
                'review_status':'approved','evidence_refs':[],'knowledge_refs':[],'source_refs':[]}]} for kind in SECTION_TYPES]
            conn.execute("""INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,input_hash,
                model_id,prompt_version,knowledge_version,policy_version,consent_refs) VALUES (%s,%s,%s,1,'published',
                %s::jsonb,%s,'synthetic-ui','synthetic-ui','knowledge:none','report-safety-v2',%s::jsonb)""",
                (report,case,run,json.dumps(sections,ensure_ascii=False),'c'*64,
                 json.dumps([{'consent_id':str(consent),'version':1,'purpose':'case_guidance'}])))
            conn.execute("""INSERT INTO report_releases(release_id,report_id,case_id,report_version,released_by,
                consent_id,consent_version,input_hash,knowledge_version,policy_version,idempotency_key,request_hash)
                VALUES (%s,%s,%s,1,%s,%s,1,%s,'knowledge:none','report-safety-v2','synthetic-ui',%s)""",
                (release,report,case,actor,consent,'c'*64,'d'*64))
            conn.execute('INSERT INTO care_outbox(outbox_id,release_id,case_id) VALUES (%s,%s,%s)',(uuid4(),release,case))
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
