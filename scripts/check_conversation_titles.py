"""Real SQL title queue checks in a disposable schema; all model calls are synthetic."""
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql
from services.api.app import conversation_repository as chats, conversation_titles as titles
from services.api.app.repository import connect, token_digest


def main():
    dsn=os.environ['ZHONGAN_DATABASE_URL']
    schema='title_test_'+uuid4().hex
    admin=connect(dsn);admin.autocommit=True
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    checks=[]
    def check(value,name):
        if not value:raise AssertionError(name)
        checks.append(name)
    try:
        with connect(dsn) as conn:
            conn.autocommit=True
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            for migration in sorted(Path('services/api/sql').glob('*.sql')):
                conn.execute(migration.read_text(encoding='utf-8'))
            actor,outsider,subject,consent=[uuid4() for _ in range(4)]
            conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s),(%s,%s)',
                         (actor,token_digest(uuid4().hex),outsider,token_digest(uuid4().hex)))
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true),(%s,%s,true,true)',
                         (actor,subject,outsider,subject))
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'synthetic',1)",(consent,subject))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())",(consent,))
            conversation=uuid4()
            chats.create_conversation(conn,actor,conversation,subject_id=subject)
            def send(question):
                turn=chats.begin_turn(conn,actor,conversation,uuid4(),question,[])
                chats.finish_turn(conn,actor,conversation,turn,answer={'text':'合成的康复回复','evidence_refs':[],'history_refs':[]})
                return turn
            send('合成问题：膝关节术后怎样复查？')
            # Emulate a legacy conversation with no title job.
            conn.execute('DELETE FROM conversation_title_jobs')
            with patch.object(titles,'generate_title',side_effect=AssertionError('GET must never call the model')):
                listed=titles.prepare_list(conn,chats.list_conversations(conn,actor))
            check(len(listed)==1 and listed[0]['title_pending'],'legacy history lazily queues title work')
            check(titles.prepare_list(conn,chats.list_conversations(conn,outsider))==[], 'same-subject other actor cannot enqueue private history')
            before=listed[0]['updated_at']
            job=titles.claim_job(conn)
            check(job is not None and titles.claim_job(conn) is None,'active lease cannot be claimed twice')
            with patch.object(titles,'generate_title',return_value=('膝关节术后复查与康复','synthetic-model')) as model:
                titles.process_job(conn,job)
            check('术后怎样复查' in model.call_args.args[0][1]['content'],'title model receives current conversation content')
            listed=titles.prepare_list(conn,chats.list_conversations(conn,actor))
            check(listed[0]['title']=='膝关节术后复查与康复' and not listed[0]['title_pending'],'AI title persists and stops polling')
            check(listed[0]['updated_at']==before and titles.claim_job(conn) is None,'title work neither reorders history nor regenerates unchanged content')
            send('合成问题：接下来如何做康复训练？')
            stale=titles.claim_job(conn)
            send('合成问题：复查日期怎么安排？')
            with patch.object(titles,'generate_title',return_value=('过时的标题','synthetic-model')):
                titles.process_job(conn,stale)
            check(chats.require_conversation(conn,actor,conversation)['title']=='膝关节术后复查与康复','stale generation cannot overwrite a newer requested title')
            job=titles.claim_job(conn)
            with patch.object(titles,'generate_title',side_effect=TimeoutError()):
                titles.process_job(conn,job)
            state=conn.execute('SELECT * FROM conversation_title_jobs').fetchone()
            check(state['status']=='queued' and state['attempts']==1,'provider failure schedules bounded retry')
            check(all(turn['status']=='completed' for turn in chats.get_turns(conn,actor,conversation)),'title failure cannot damage delivered chat replies')
            # Reclaim an expired worker lease; old result must no longer apply.
            conn.execute("UPDATE conversation_title_jobs SET next_attempt_at=now()")
            old=titles.claim_job(conn)
            conn.execute("UPDATE conversation_title_jobs SET lease_expires_at=now()-interval '1 second'")
            newer=titles.claim_job(conn)
            titles._finish(conn,old,title='旧任务结果',model_id='synthetic',actor=actor)
            check(newer['lease_token']!=old['lease_token'] and conn.execute('SELECT status FROM conversation_title_jobs').fetchone()['status']=='running','expired lease result is ignored')
            conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
            with patch.object(titles,'generate_title') as model:
                titles.process_job(conn,newer)
            check(not model.called and conn.execute('SELECT status FROM conversation_title_jobs').fetchone()['status']=='failed','revoked consent stops queued model processing')
            # Also recheck authorization after an in-flight model call.
            conn.execute("UPDATE consent_purposes SET status='active' WHERE consent_id=%s",(consent,))
            send('合成问题：整理本次复查计划')
            job=titles.claim_job(conn)
            def revoke(_messages):
                conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
                return '不可应用的标题','synthetic-model'
            with patch.object(titles,'generate_title',side_effect=revoke):
                titles.process_job(conn,job)
            check(chats.list_conversations(conn,actor)==[] and conn.execute('SELECT title FROM conversations').fetchone()['title']=='膝关节术后复查与康复','revocation during generation prevents title application')
        print(json.dumps({'status':'passed','checks':checks,'count':len(checks),'mode':'synthetic-model/real-SQL'},ensure_ascii=False))
    finally:
        admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


if __name__=='__main__':main()
