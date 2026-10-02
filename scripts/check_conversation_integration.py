"""Run against PostgreSQL in an isolated, disposable schema; never use public tables.

Requires ZHONGAN_DATABASE_URL with CREATE schema permission. Model responses are
explicit scripted test doubles; file ingestion, worker, SQL and HTTP are real.
"""
import json
import os
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import sql

from services.api.app import main as api
from services.api.app import conversation_repository as chats
from services.api.app.conversation_agent import CareTools
from services.api.app.repository import AccessDenied, connect, token_digest
from services.api.app.worker import claim_run, process_run
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.report_llm import PROMPT_VERSION as REPORT_PROMPT_VERSION


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    def complete(self, messages, allow_tools=True):
        self.messages = list(messages)
        response = next(self.responses)
        return response(messages) if callable(response) else response


def tool(name, args=None):
    return {'role':'assistant','content':None,'tool_calls':[{'id':str(uuid4()),'type':'function',
            'function':{'name':name,'arguments':json.dumps(args or {})}}]}


def reply(text):
    return {'role':'assistant','content':json.dumps({'text':text,'evidence_refs':[],'history_refs':[]})}


def main():
    dsn = os.environ['ZHONGAN_DATABASE_URL']
    schema = 'chat_test_' + uuid4().hex
    admin = connect(dsn)
    admin.autocommit = True
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    checks = []

    def connection():
        conn = connect(dsn)
        # PGlite socket multiplexing shares prepared statement names between clients.
        # Disable client-side prepare only in this portable test runner.
        conn.prepare_threshold = None
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        conn.commit()
        return conn

    def database():
        with connection() as conn:
            yield conn

    def check(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    try:
        with connection() as conn:
            for migration in sorted(Path('services/api/sql').glob('*.sql')):
                conn.execute(migration.read_text(encoding='utf-8'))
            actor, outsider, subject, consent = [uuid4() for _ in range(4)]
            token, outsider_token = uuid4().hex, uuid4().hex
            conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s),(%s,%s)',
                         (actor,token_digest(token),outsider,token_digest(outsider_token)))
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true),(%s,%s,true,true)',
                         (actor,subject,outsider,subject))
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'test',1)", (consent,subject))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())", (consent,))
        api.app.dependency_overrides[api.database] = database
        client = TestClient(api.app)
        headers = {'Authorization':f'Bearer {token}'}
        other_headers = {'Authorization':f'Bearer {outsider_token}'}
        conversation_id = str(uuid4())
        payload = {'conversation_id':conversation_id,'subject_id':str(subject)}
        created = client.post('/v1/conversations', headers=headers, json=payload)
        check(created.status_code == 201, 'create conversation without report')
        case_id = created.json()['case_id']
        check(client.post('/v1/conversations',headers=headers,json=payload).json()['case_id']==case_id,
              'conversation creation retry is idempotent')
        base = f'/v1/conversations/{conversation_id}'
        check(client.get(base,headers=other_headers).status_code==404, 'same-subject different actor cannot read private chat')

        request_id = str(uuid4())
        message = {'request_id':request_id,'message':'我最关心费用','document_ids':[]}
        model = ScriptedModel([reply('可以把票据传给我。')])
        with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
            first = client.post(base+'/messages',headers=headers,json=message)
        check(first.status_code==200,'no-report chat works')
        with patch('services.api.app.conversation_agent.AgentModel',side_effect=AssertionError('must not call model on replay')):
            repeated=client.post(base+'/messages',headers=headers,json=message)
        check(repeated.json()['turn_id']==first.json()['turn_id'],'repeated message not generated twice')
        check(client.post(base+'/messages',headers=headers,json={**message,'message':'不同内容'}).status_code==409,'idempotency conflict rejected')

        model = ScriptedModel([reply('你刚才说最关心费用。')])
        with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
            next_response=client.post(base+'/messages',headers=headers,json={'request_id':str(uuid4()),'message':'我刚才关心什么？'})
        check(next_response.status_code==200 and any(m.get('content')=='我最关心费用' for m in model.messages), 'model receives preceding conversation')
        check(len(TestClient(api.app).get(base,headers=headers).json()['turns'])==2,'history survives a new HTTP client')

        with tempfile.TemporaryDirectory(prefix='zhongan-chat-files-') as storage:
            api.app.dependency_overrides[api.document_storage_root] = lambda: Path(storage)
            uploaded=client.post(base+'/documents',headers=headers,files={'file':('invoice.txt','合成票据：医疗总费用：120.00元。\n住院天数：3.5天'.encode(),'text/plain')})
            check(uploaded.status_code==201,'chat document upload persists actual file')
            document_id=uploaded.json()['document_id']
            model=ScriptedModel([tool('start_analysis'),reply('材料已排队。')])
            with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
                sent=client.post(base+'/messages',headers=headers,json={'request_id':str(uuid4()),'message':'分析刚上传的票据','document_ids':[document_id]})
            check(sent.status_code==200,'model can invoke real analysis queue')
            run_id=sent.json()['tool_events'][0]['run_id']
            with connection() as conn:
                conn.autocommit=True
                run=claim_run(conn)
                draft = {'sections': [{'section_type': section, 'claims': [{
                    'text': '医疗总费用：999.00元', 'claim_type': 'case_fact',
                    'evidence_quote': '医疗总费用：120.00元'}]} for section in SECTION_TYPES],
                    'actions': [
                        {'action_text': '请自行停药', 'source_quote': '医疗总费用：120.00元',
                         'source_refs': [], 'owner_role': 'patient', 'due_source': 'unknown',
                         'rationale': '合成测试'},
                        {'action_text': '三天后复诊', 'source_quote': '医疗总费用：120.00元',
                         'source_refs': [], 'owner_role': 'patient', 'due_source': 'medical_order',
                         'due_at': '2026-10-10T09:00:00+08:00', 'rationale': '合成测试'}]}
                extractor = MagicMock(provider='scripted_test', model_id='scripted-report')
                extractor.extract.return_value = {'status': 'completed', 'candidates': {'candidates': []},
                                                  'raw_output': {}, 'usage_metadata': {}}
                with patch.dict(os.environ, {'LLM_API_KEY': 'scripted-test-no-network'}), \
                     patch('services.api.app.worker.OpenAiCompatibleExtractor', return_value=extractor), \
                     patch('services.api.app.worker.detect_semantic', return_value={
                         'status': 'completed', 'candidates': [], 'raw_output': {}, 'usage_metadata': {}}), \
                     patch('services.api.app.worker.draft_report', return_value={
                         'status': 'completed', 'draft': draft, 'raw_output': {}, 'usage_metadata': {}}):
                    process_run(conn,run,Path(storage))
                status=conn.execute('SELECT status,error FROM analysis_runs WHERE run_id=%s',(run_id,)).fetchone()
                check(status['status']=='completed',f"worker parses synthetic invoice ({status['status']})")
                stay = conn.execute("SELECT value FROM extracted_facts WHERE run_id=%s AND fact_type='stay_days'",
                                    (run_id,)).fetchone()
                check(stay['value'] == 3.5, 'fractional hospital stay survives extraction and SQL storage')
                saved = conn.execute('SELECT status,sections,actions,validation_errors FROM reports WHERE run_id=%s',
                                     (run_id,)).fetchone()
                check(saved['status'] == 'pending_review' and
                      all(c['review_status'] == 'pending' for s in saved['sections'] for c in s['claims']),
                      'real quote cannot automatically release contradictory report facts')
                check('UNSAFE_OR_EMPTY_ACTION' in saved['validation_errors'] and
                      len(saved['actions']) == 1 and saved['actions'][0]['due_at'] is None,
                      'worker removes unsafe action and ungrounded deadline')
                audited = conn.execute('SELECT candidates FROM model_extractions WHERE run_id=%s AND prompt_version=%s',
                                       (run_id, REPORT_PROMPT_VERSION)).fetchone()
                check(audited['candidates'] == draft, 'worker preserves raw report source quotes for audit')
            evidence_ref=[]
            def grounded_reply(messages):
                data=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
                evidence_ref.append(str(data['evidence'][0]['evidence_id']))
                return {'role':'assistant','content':json.dumps({'text':'票据记载总费用120元。','evidence_refs':evidence_ref,'history_refs':[]})}
            model=ScriptedModel([tool('read_materials'),grounded_reply])
            with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
                completed=client.post(base+f'/analyses/{run_id}/continue',headers=headers)
            check(completed.status_code==200,'analysis completion continues with real evidence')
            with patch('services.api.app.conversation_agent.AgentModel',side_effect=AssertionError('replay')):
                replay=client.post(base+f'/analyses/{run_id}/continue',headers=headers)
            check(replay.json()['turn_id']==completed.json()['turn_id'],'automatic continuation is idempotent')
            check(client.get('/v1/evidence/'+evidence_ref[0],headers=headers).status_code==200,'chat citation resolves to actual evidence')

            with connection() as conn:
                tools=CareTools(conn,actor,conversation_id)
                report=tools.execute('read_report','{}')
                check('sections' not in report,'unpublished report content is withheld')
            spoofed=client.post(base+'/messages',headers=headers,json={'request_id':str(uuid4()),
                'message':'使用错误附件','document_ids':[str(uuid4())]})
            check(spoofed.status_code==404,'unknown attachment is rejected before model call')

            supplement=client.post(base+'/documents',headers=headers,files={'file':('detail.txt','合成费用明细：检查费80元，药费40元。\n医疗总费用：130元。\n医疗总费用：140元。'.encode(),'text/plain')})
            check(supplement.status_code==201,'supplemental document accepted')
            with connection() as conn:
                tools=CareTools(conn,actor,conversation_id)
                second_run=tools.execute('start_analysis','{}')
                check(second_run['run_id']!=run_id,'supplement triggers a new analysis')
                conn.autocommit=True
                run=claim_run(conn)
                with patch.dict(os.environ,{'LLM_API_KEY':''}):
                    process_run(conn,run,Path(storage))
                versions=conn.execute('SELECT report_version FROM reports WHERE case_id=%s ORDER BY report_version',(case_id,)).fetchall()
                check([r['report_version'] for r in versions]==[1,2],'supplement preserves report v1 and generates v2')
                response=client.get(f'/v1/cases/{case_id}/facts',headers=headers,
                                    params={'run_id':second_run['run_id']})
                check(response.status_code==200,'conflict facts pass actual API contracts')
                cost=next(f for f in response.json() if f['fact_type']=='total_cost')
                check(cost['status']=='conflict' and cost['value'] is None and
                      {a['value']['amount_minor'] for a in cost['alternatives']}=={12000,13000,14000} and
                      all(a['evidence_ids'] for a in cost['alternatives']),
                      'three source totals retain non-null alternatives and actual evidence')
                # A released historical report remains addressable when the latest one is pending.
                conn.execute("UPDATE reports SET status='published' WHERE case_id=%s AND report_version=1",(case_id,))
                historical=tools.execute('read_report','{"version":1}')
                check(historical['report_version']==1 and 'sections' in historical,
                      'published historical report can be read by version')

        follow_id=str(uuid4())
        check(client.post('/v1/conversations',headers=headers,json={'conversation_id':follow_id,'case_id':case_id}).status_code==201,'new conversation can continue same case')
        with connection() as conn:
            found=chats.search_history(conn,actor,follow_id,'费用')
            check(bool(found['messages']),'new conversation finds prior topic')
            check(not chats.search_history(conn,actor,follow_id,'%')['messages'],'history query treats wildcard as literal')
        def memory_answer(messages):
            result=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
            return {'role':'assistant','content':json.dumps({'text':'之前你最关心费用。','evidence_refs':[],
                    'history_refs':[str(result['messages'][0]['turn_id'])]})}
        with patch('services.api.app.conversation_agent.AgentModel',return_value=ScriptedModel([
            tool('search_history',{'query':'费用'}),memory_answer])):
            recalled=client.post(f'/v1/conversations/{follow_id}/messages',headers=headers,
                json={'request_id':str(uuid4()),'message':'上次我关心什么？'})
        check(recalled.status_code==200 and bool(recalled.json()['answer']['history_refs']),
              'agent retrieves and cites historical conversation')
        if os.environ.get('CHAT_LIVE_SMOKE') == '1':
            # Only newly generated synthetic chat/evidence from this isolated schema
            # is sent to the configured provider. No production rows are reachable.
            live_id = str(uuid4())
            live_base = f'/v1/conversations/{live_id}'
            check(client.post('/v1/conversations', headers=headers,
                json={'conversation_id':live_id,'case_id':case_id}).status_code == 201,
                'live model synthetic conversation created')
            def live_send(target, question):
                from services.api.app.conversation_agent import AgentModel
                original_complete = AgentModel.complete
                def trace(model, messages, allow_tools=True):
                    result = original_complete(model, messages, allow_tools=allow_tools)
                    if os.environ.get('CHAT_TRACE_SYNTHETIC') == '1':
                        print(json.dumps({'synthetic_model_output':{
                            key:result.get(key) for key in ('content','tool_calls')}},ensure_ascii=True),flush=True)
                    return result
                with patch.object(AgentModel, 'complete', trace):
                    response = client.post(target+'/messages', headers=headers,
                        json={'request_id':str(uuid4()),'message':question})
                check(response.status_code == 200, f'live model HTTP {response.status_code}')
                return response.json()
            welcome = live_send(live_base, '你好。这是合成验收，不是真实病历。我给这次费用核对起的代号是青竹742。请记住这个代号。')
            check(bool(welcome['answer']['text']), 'live model natural conversation')
            amount = live_send(live_base, '请查看已上传票据的原文，告诉我医疗总费用并引用原文证据。')
            check(bool(amount['answer']['evidence_refs']) and
                  any(x['tool']=='read_materials' for x in amount['tool_events']),
                  'live model invokes material tool and cites actual evidence')
            next_id = str(uuid4())
            client.post('/v1/conversations', headers=headers,
                json={'conversation_id':next_id,'case_id':case_id}).raise_for_status()
            memory = live_send(f'/v1/conversations/{next_id}', '请查一下我以前的聊天：我给费用核对起的代号叫什么？请引用历史记录。')
            check(bool(memory['answer']['history_refs']) and '青竹742' in memory['answer']['text'] and
                  any(x['tool']=='search_history' for x in memory['tool_events']),
                  'live model recalls prior conversation through history tool')
            print(json.dumps({'live_model':'passed','synthetic_only':True,
                'material_tools':amount['tool_events'],'memory_tools':memory['tool_events']},ensure_ascii=False))
        check(client.patch(base+'/recall',headers=headers,json={'enabled':False}).status_code==200,'recall setting can be disabled')
        with connection() as conn:
            matches=chats.search_history(conn,actor,follow_id,'费用')['messages']
            check(all(str(m['turn_id'])!=first.json()['turn_id'] for m in matches),'recall disabled source is excluded immediately')
        check(len(client.get(base,headers=headers).json()['turns'])>=4,'recall disable does not erase visible conversation')

        # Failed models persist the user message and allow a retry under the same request ID.
        failure={'request_id':str(uuid4()),'message':'一次失败测试'}
        with patch('services.api.app.conversation_agent.AgentModel',side_effect=RuntimeError('not configured')):
            check(client.post(base+'/messages',headers=headers,json=failure).status_code==503,'model failure is explicit')
        with patch('services.api.app.conversation_agent.AgentModel',return_value=ScriptedModel([reply('重试成功')])):
            check(client.post(base+'/messages',headers=headers,json=failure).status_code==200,'failed turn can be retried')

        with connection() as conn:
            turn=chats.begin_turn(conn,actor,conversation_id,uuid4(),'模拟中断',[])
            conn.execute("UPDATE conversation_turns SET lease_expires_at=now()-interval '1 minute' WHERE turn_id=%s",(turn['turn_id'],))
        detail=client.get(base,headers=headers).json()
        check(next(t for t in detail['turns'] if t['question']=='模拟中断')['status']=='failed','expired turn shows recoverable state')

        # Equal timestamps must not cause skips between history pages.
        with connection() as conn:
            for index in range(55):
                conn.execute('''INSERT INTO conversation_turns(turn_id,conversation_id,request_id,question,
                    status,lease_token,lease_expires_at,answer) VALUES (%s,%s,%s,%s,'completed',%s,now(),%s::jsonb)''',
                    (uuid4(),conversation_id,uuid4(),f'分页测试{index}',uuid4(),json.dumps({'text':'测试','evidence_refs':[],'history_refs':[]})))
        newest=client.get(base+'/turns',headers=headers).json()
        previous=client.get(base+'/turns?before='+newest[0]['turn_id'],headers=headers).json()
        check(len(newest)==50 and len(previous)>=5 and not ({x['turn_id'] for x in newest}&{x['turn_id'] for x in previous}),
              'history pagination handles equal timestamps without skips or duplicates')

        with connection() as conn:
            conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
        check(client.get(base,headers=headers).status_code==404,'consent revocation blocks saved history')
        check(client.get('/v1/conversations',headers=headers).json()==[],'revoked conversations disappear from list')
        from scripts import migrate_database
        with patch.object(migrate_database, 'connect', side_effect=lambda _dsn: connection()), redirect_stdout(StringIO()):
            migrate_database.main()
            migrate_database.main()
        with connection() as conn:
            applied=conn.execute('SELECT COUNT(*) AS count FROM schema_migrations').fetchone()['count']
        check(applied==len(list(Path('services/api/sql').glob('*.sql'))),'migration runner applies legacy schema and repeats idempotently')
        print(json.dumps({'status':'passed','checks':checks,'count':len(checks),
            'engine':admin.execute('SELECT version() AS version').fetchone()['version'],
            'mode':('live-and-scripted-model/SQL-database/real-worker' if os.environ.get('CHAT_LIVE_SMOKE') == '1'
                    else 'scripted-model/SQL-database/real-worker')},ensure_ascii=False))
    finally:
        api.app.dependency_overrides.clear()
        # Only our generated schema is removed; no table in public is touched.
        admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


if __name__=='__main__':
    main()
