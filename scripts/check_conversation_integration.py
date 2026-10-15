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
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg import sql

from services.api.app import main as api
from services.api.app import conversation_repository as chats
from services.api.app.conversation_agent import CareTools, ANALYSIS_PROMPT_VERSION
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
            uploaded=client.post(base+'/documents',headers=headers,files={'file':('invoice.txt','合成票据：医疗总费用：120.00元。\n药品费：40元\n检查费：80元\n明细合计：120元\n个人自费：10元\n现金支付：30元\n住院天数：3.5天\nCT提示不能排除肺炎。'.encode(),'text/plain')})
            check(uploaded.status_code==201,'chat document upload persists actual file')
            document_id=uploaded.json()['document_id']
            user_context={'concern':'担心费用，希望核对两个支付金额'}
            with connection() as conn:
                conn.execute('UPDATE cases SET user_context=%s::jsonb WHERE case_id=%s',
                             (json.dumps(user_context),case_id))
            check(client.patch(base+'/report-context',headers=other_headers,json={'enabled':True}).status_code==404,
                  'same-case other actor cannot authorize private chat for reports')
            check(client.get(base,headers=headers).json()['conversation']['report_context_enabled'] is False,
                  'chat report context sharing is disabled by default')
            enabled=client.patch(base+'/report-context',headers=headers,json={'enabled':True})
            check(enabled.status_code==200,'owner explicitly authorizes current chat expressions for case reports')
            model=ScriptedModel([tool('start_analysis'),reply('材料已排队。')])
            with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
                sent=client.post(base+'/messages',headers=headers,json={'request_id':str(uuid4()),'message':'分析刚上传的票据','document_ids':[document_id]})
            check(sent.status_code==200,'model can invoke real analysis queue')
            run_id=sent.json()['tool_events'][0]['run_id']
            with connection() as conn:
                conn.autocommit=True
                run=claim_run(conn)
                conn.execute("UPDATE analysis_runs SET lease_expires_at=now()-interval '1 second' WHERE run_id=%s",
                             (run['run_id'],))
                conn.execute('UPDATE cases SET user_context=%s::jsonb WHERE case_id=%s',
                             (json.dumps({'concern':'后来修改的上下文不应覆盖快照'}),case_id))
                context_snapshot=run['context_snapshot']
                check(context_snapshot['case_user_context']==user_context and
                      [t['text'] for t in context_snapshot['chat']['turns']]==[
                          '我最关心费用','我刚才关心什么？','分析刚上传的票据'],
                      'analysis freezes only owner user utterances through the initiating turn')
                chat_ref=f"conversation:{conversation_id}:turn:{context_snapshot['chat']['turns'][0]['turn_id']}:user"
                draft = {'sections': [{'section_type': section, 'claims': [{
                    'text': '医疗总费用：999.00元', 'claim_type': 'case_fact',
                    'evidence_quote': '医疗总费用：120.00元'}]} for section in SECTION_TYPES],
                    'actions': [
                        {'action_text': '请自行停药', 'source_quote': '医疗总费用：120.00元',
                         'source_refs': [], 'owner_role': 'patient', 'due_source': 'unknown',
                         'rationale': '合成测试'},
                        {'action_text': '三天后复诊', 'source_quote': '医疗总费用：120.00元',
                         'source_refs': [], 'owner_role': 'patient', 'due_source': 'medical_order',
                         'due_at': '2026-10-10T09:00:00+08:00', 'rationale': '合成测试'},
                        {'action_text':'向客服核对费用疑问','source_quote':'我最关心费用',
                         'source_refs':[], 'owner_role':'patient','due_source':'unknown','due_at':None,
                         'rationale':'用户明确表达的费用疑问'}]}
                draft['sections'][4]['claims'].append({'text':'你最关心费用',
                    'claim_type':'patient_statement','source_quote':'我最关心费用','source_refs':[]})
                extractor = MagicMock(provider='scripted_test', model_id='scripted-report')
                extractor.extract.return_value = {'status': 'completed', 'candidates': {'candidates': [{
                    'fact_type': 'diagnosis', 'raw_value': '肺炎', 'normalized_value': '肺炎',
                    'assertion': 'present', 'evidence_quote': '肺炎'}]},
                                                  'raw_output': {}, 'usage_metadata': {}}
                def draft_with_lease_check(*args, **kwargs):
                    lease = conn.execute("SELECT lease_expires_at > now()+interval '4 minutes' AS renewed FROM analysis_runs WHERE run_id=%s",
                                         (run['run_id'],)).fetchone()
                    check(lease['renewed'], 'worker renews the lease before the longer report request')
                    return {'status': 'completed', 'draft': draft, 'raw_output': {}, 'usage_metadata': {}}
                with patch.dict(os.environ, {'LLM_API_KEY': 'scripted-test-no-network'}), \
                     patch('services.api.app.worker.OpenAiCompatibleExtractor', return_value=extractor), \
                     patch('services.api.app.worker.detect_semantic', return_value={
                         'status': 'completed', 'candidates': [], 'raw_output': {}, 'usage_metadata': {}}), \
                     patch('services.api.app.worker.draft_report', side_effect=draft_with_lease_check) as report_drafter:
                    process_run(conn,run,Path(storage))
                status=conn.execute('SELECT status,error FROM analysis_runs WHERE run_id=%s',(run_id,)).fetchone()
                check(status['status']=='completed',f"worker parses synthetic invoice ({status['status']})")
                stay = conn.execute("SELECT value FROM extracted_facts WHERE run_id=%s AND fact_type='stay_days'",
                                    (run_id,)).fetchone()
                cost_events=conn.execute("SELECT attributes->>'fact_type' AS fact_type FROM medical_events WHERE run_id=%s AND event_type='cost'",
                                         (run_id,)).fetchall()
                check({row['fact_type'] for row in cost_events}=={'total_cost','cost_breakdown'},
                      'scalar total and structured costs persist as distinct source-bound events')
                check(stay['value'] == 3.5, 'fractional hospital stay survives extraction and SQL storage')
                response=client.get(f'/v1/cases/{uploaded.json()["case_id"]}/facts',headers=headers,
                                    params={'run_id':run_id})
                check(response.status_code==200 and next(f for f in response.json()
                      if f['fact_type']=='diagnosis')['assertion']=='unknown',
                      'model cannot confirm a diagnosis by quoting only the uncertain entity')
                costs=next(f for f in response.json() if f['fact_type']=='cost_breakdown')
                fields={f['source_label']:f for f in costs['value']['fields']}
                check(costs['status']=='derived' and fields['药品费']['amount']['value']['amount_minor']==4000 and
                      fields['个人自费']['role']=='payment_component' and costs['value']['self_paid_ratio'] is None,
                      'worker stores source-bound cost categories and separate payment labels without inferred ratios')
                cost_refs={str(src['evidence_id']) for f in fields.values() for src in f['sources']}
                check(cost_refs==set(costs['evidence_ids']) and all(client.get(f'/v1/evidence/{ref}',headers=headers).status_code==200
                      for ref in cost_refs),'cost component references resolve through the actual authorized evidence API')
                conn.execute('UPDATE actor_subject_access SET can_read_case=false WHERE actor_id=%s',(outsider,))
                check(client.get(f'/v1/cases/{uploaded.json()["case_id"]}/facts',headers=other_headers,
                      params={'run_id':run_id}).status_code==404 and all(client.get(f'/v1/evidence/{ref}',headers=other_headers).status_code==404
                      for ref in cost_refs),'unscoped actor cannot read cost components or their evidence')
                conn.execute('UPDATE actor_subject_access SET can_read_case=true WHERE actor_id=%s',(outsider,))
                context=report_drafter.call_args.kwargs['structured_costs']
                check(any(f['source_label']=='药品费' and f['value']['amount_minor']==4000 for f in context['fields']) and
                      context['completeness_status']=='not_established','report generation receives source-bound cost fields and limitations')
                saved = conn.execute('SELECT status,sections,actions,validation_errors FROM reports WHERE run_id=%s',
                                     (run_id,)).fetchone()
                check(conn.execute("SELECT count(*) AS n FROM review_tasks WHERE run_id=%s AND target_type='report' AND status='pending'",
                                   (run_id,)).fetchone()['n']==1, 'worker queues pending report for actual review')
                check(saved['status'] == 'pending_review' and
                      all(c['review_status'] == 'pending' for s in saved['sections'] for c in s['claims']),
                      'real quote cannot automatically release contradictory report facts')
                concern=saved['sections'][4]['claims'][-1]
                check(concern['claim_type']=='patient_statement' and concern['source_refs']==[chat_ref]
                      and not concern['evidence_refs'] and report_drafter.call_args.args[2]==user_context,
                      'worker retains user concern with separate source provenance and review status')
                check('UNSAFE_OR_EMPTY_ACTION' in saved['validation_errors'] and
                      len(saved['actions']) == 2 and saved['actions'][0]['due_at'] is None and
                      saved['actions'][1]['source_refs']==[chat_ref],
                      'worker removes unsafe action and ungrounded deadline')
                audited = conn.execute('SELECT candidates FROM model_extractions WHERE run_id=%s AND prompt_version=%s',
                                       (run_id, REPORT_PROMPT_VERSION)).fetchone()
                check(audited['candidates'] == draft, 'worker preserves raw report source quotes for audit')
            material=client.get(base,headers=headers).json()['material_report']
            check(material['status']=='available' and material['pending_count']>0,
                  'pending clinical report has an independent readable material report')
            material_text=json.dumps(material,ensure_ascii=False)
            check('999.00' not in material_text and '自行停药' not in material_text and '不能排除肺炎' in material_text,
                  'automatic material report excludes fabricated conclusions and preserves uncertain source wording')
            check(client.get(base,headers=other_headers).status_code==404,
                  'material report remains private to conversation owner')
            with connection() as conn:
                checked_tools=CareTools(conn,actor,conversation_id)
                checked=checked_tools.execute('read_material_report','{}')
                check(checked['report_id']==material['report_id'] and bool(checked_tools.evidence_ids),
                      'follow-up agent can read the same checked material report and cite its evidence')
            evidence_ref=[]
            def grounded_reply(messages):
                data=json.loads(next(m['content'] for m in reversed(messages)
                                     if 'authorized_material_pages' in (m.get('content') or '')))['authorized_material_pages'][0]
                evidence_ref.append(data['spans'][0][0])
                return {'role':'assistant','content':json.dumps({'text':'票据记载总费用120元。','evidence_refs':evidence_ref,'history_refs':[], 'citations':[{'quote':'票据记载总费用120元。','source_refs':evidence_ref}]})}
            model=ScriptedModel([grounded_reply])
            with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
                completed=client.post(base+f'/analyses/{run_id}/continue',headers=headers)
            check(completed.status_code==200,'analysis completion continues with real evidence')
            check(completed.json()['answer']['analysis_run_id']==str(run_id) and
                  completed.json()['answer']['prompt_version']==ANALYSIS_PROMPT_VERSION,
                  'personal narrative is model-generated and bound to the exact analysis run')
            with patch('services.api.app.conversation_agent.AgentModel',side_effect=AssertionError('replay')):
                replay=client.post(base+f'/analyses/{run_id}/continue',headers=headers)
            check(replay.json()['turn_id']==completed.json()['turn_id'],'automatic continuation is idempotent')
            check(client.get('/v1/evidence/'+completed.json()['answer']['evidence_refs'][0],headers=headers).status_code==200,'compact source alias resolves to actual accessible evidence')

            with connection() as conn:
                tools=CareTools(conn,actor,conversation_id)
                report=tools.execute('read_report','{}')
                check('sections' not in report,'unpublished report content is withheld')
            spoofed=client.post(base+'/messages',headers=headers,json={'request_id':str(uuid4()),
                'message':'使用错误附件','document_ids':[str(uuid4())]})
            check(spoofed.status_code==404,'unknown attachment is rejected before model call')

            supplement=client.post(base+'/documents',headers=headers,files={'file':('detail.txt','合成费用明细：检查费80元，药费40元。\n医疗总费用：130元。\n医疗总费用：140元。'.encode(),'text/plain')})
            check(supplement.status_code==201,'supplemental document accepted')
            with patch('services.api.app.conversation_agent.AgentModel',side_effect=AssertionError('stale cache must not invoke a model')):
                stale=client.post(base+f'/analyses/{run_id}/continue',headers=headers)
            check(stale.status_code==409,'new material invalidates cached continuation before another analysis is queued')
            with connection() as conn:
                tools=CareTools(conn,actor,conversation_id,sent.json()['turn_id'])
                second_run=tools.execute('start_analysis','{}')
                check(second_run['run_id']!=run_id,'supplement triggers a new analysis')
                repeated=tools.execute('start_analysis','{}')
                check(repeated['run_id']==second_run['run_id'],
                      'same initiating turn with identical materials reuses the frozen run')
                conn.autocommit=True
                run=claim_run(conn)
                with patch.dict(os.environ,{'LLM_API_KEY':''}):
                    process_run(conn,run,Path(storage))
                versions=conn.execute('SELECT report_version FROM reports WHERE case_id=%s ORDER BY report_version',(case_id,)).fetchall()
                check([r['report_version'] for r in versions]==[1,2],'supplement preserves report v1 and generates v2')
                check(conn.execute("SELECT status FROM review_tasks WHERE run_id=%s AND target_type='report'",
                                   (run_id,)).fetchone()['status']=='cancelled',
                      'new report cancels superseded pending review task')
                response=client.get(f'/v1/cases/{case_id}/facts',headers=headers,
                                    params={'run_id':second_run['run_id']})
                check(response.status_code==200,'conflict facts pass actual API contracts')
                cost=next(f for f in response.json() if f['fact_type']=='total_cost')
                check(cost['status']=='conflict' and cost['value'] is None and
                      {a['value']['amount_minor'] for a in cost['alternatives']}=={12000,13000,14000} and
                      all(a['evidence_ids'] for a in cost['alternatives']),
                      'three source totals retain non-null alternatives and actual evidence')
                # Historical-read fixture only; actual release gates are tested separately.
                # This explicit synthetic state is not evidence that the model's unsafe draft can publish.
                safe_sections=[{'section_type': kind,'claims':[{'claim_id':str(uuid4()),
                    'text':'合成历史报告：相关信息仍需结合原始材料核对。','claim_type':'to_confirm',
                    'evidence_refs':[],'knowledge_refs':[],'source_refs':[],'review_status':'approved'}]}
                    for kind in SECTION_TYPES]
                conn.execute("UPDATE reports SET status='published',sections=%s::jsonb,actions='[]',validation_errors='[]' WHERE case_id=%s AND report_version=1",
                             (json.dumps(safe_sections,ensure_ascii=False),case_id))
                conn.execute("""INSERT INTO report_releases(release_id,report_id,case_id,report_version,released_by,
                    consent_id,consent_version,input_hash,knowledge_version,policy_version,idempotency_key,request_hash)
                    SELECT %s,report_id,case_id,report_version,%s,%s,1,input_hash,knowledge_version,policy_version,
                    'historical-read-fixture',%s FROM reports WHERE case_id=%s AND report_version=1""",
                    (uuid4(),actor,consent,'f'*64,case_id))
                historical=tools.execute('read_report','{"version":1}')
                check(historical['report_version']==1 and 'sections' in historical,
                      'published historical report can be read by version')

        # ---- Report-context lifecycle on a dedicated conversation ----
        # truncation, anchor dedupe, immutable snapshot, disable semantics and
        # the late-worker rejection after the owner withdraws sharing.
        with tempfile.TemporaryDirectory(prefix='zhongan-context-files-') as ctx_storage:
            api.app.dependency_overrides[api.document_storage_root] = lambda: Path(ctx_storage)
            conv2 = str(uuid4())
            c2 = f'/v1/conversations/{conv2}'
            created2 = client.post('/v1/conversations', headers=headers, json={'conversation_id': conv2})
            check(created2.status_code == 201, 'context lifecycle conversation created')
            check(client.get(c2, headers=headers).json()['conversation']['report_context_enabled'] is False,
                  'second conversation also defaults to private')
            up2 = client.post(c2 + '/documents', headers=headers,
                              files={'file': ('note.txt', '合成材料：医疗总费用：60.00元。'.encode(), 'text/plain')})
            check(up2.status_code == 201, 'context lifecycle upload accepted')
            doc2 = up2.json()['document_id']
            client.patch(c2 + '/report-context', headers=headers, json={'enabled': True}).raise_for_status()

            def send2(text, docs=None):
                responses = [tool('start_analysis'), reply('材料已排队。')] if docs else [reply('收到。')]
                with patch('services.api.app.conversation_agent.AgentModel',
                           return_value=ScriptedModel(responses)):
                    r = client.post(c2 + '/messages', headers=headers,
                                    json={'request_id': str(uuid4()), 'message': text, 'document_ids': docs or []})
                check(r.status_code == 200, f'context lifecycle message delivered: {text[:12]}')
                return r.json()

            for index in range(13):
                send2(f'关切{index:02d}')
            final = send2('请分析这份材料', docs=[doc2])
            run2_id = final['tool_events'][0]['run_id']
            with connection() as conn:
                conn.autocommit = True
                snapshot = conn.execute('SELECT context_snapshot FROM analysis_runs WHERE run_id=%s',
                                        (run2_id,)).fetchone()['context_snapshot']
                texts = [t['text'] for t in snapshot['chat']['turns']]
                check(snapshot['chat']['truncated'] is True and len(texts) == 12 and
                      texts[0] == '关切02' and texts[-1] == '请分析这份材料',
                      'snapshot keeps the latest 12 owner utterances and marks truncation')
                check(all('assistant' not in json.dumps(t) for t in snapshot['chat']['turns']),
                      'model answers never enter the frozen user expression list')
                try:
                    conn.execute('UPDATE analysis_runs SET context_snapshot=%s WHERE run_id=%s',
                                 (json.dumps({'tampered': True}), run2_id))
                    check(False, 'context snapshot must be immutable')
                except Exception:
                    check(conn.execute('SELECT context_snapshot FROM analysis_runs WHERE run_id=%s',
                                       (run2_id,)).fetchone()['context_snapshot'] == snapshot,
                          'immutable trigger blocks snapshot tampering')
                tools2 = CareTools(conn, actor, conv2, UUID(final['turn_id']))
                check(tools2.execute('start_analysis', '{}')['run_id'] == run2_id,
                      'duplicate tool call on the same initiating turn reuses the frozen run')
                with patch.dict(os.environ, {'LLM_API_KEY': ''}):
                    claimed = claim_run(conn)
                    check(claimed is not None and str(claimed['run_id']) == run2_id,
                          'context lifecycle run is queued for the worker')
                    process_run(conn, claimed, Path(ctx_storage))
                check(conn.execute('SELECT status FROM analysis_runs WHERE run_id=%s',
                                   (run2_id,)).fetchone()['status'] == 'completed',
                      'run with frozen context completes without a model key on synthetic text')
                # Sharing is still on with the original version: the report should be visible.
                rep_row = conn.execute('SELECT report_id FROM reports WHERE run_id=%s LIMIT 1',
                                       (run2_id,)).fetchone()
                check(rep_row is not None, 'run2 report exists after processing')
                if rep_row:
                    rep_id = rep_row['report_id']
                    # Clear pending review statuses so the visibility check passes;
                    # the test targets sharing-withdrawal visibility, not review gates.
                    conn.execute("""UPDATE reports SET status='published', sections=(
                        SELECT jsonb_agg(jsonb_set(claim_row, '{claims}',
                            (SELECT jsonb_agg(jsonb_set(c, '{review_status}', '"approved"'))
                             FROM jsonb_array_elements(claim_row->'claims') c))
                        ) FROM jsonb_array_elements(sections) claim_row) WHERE report_id=%s""", (rep_id,))
                    conn.execute("""INSERT INTO report_releases(release_id,report_id,case_id,report_version,
                        released_by,consent_id,consent_version,input_hash,knowledge_version,policy_version,
                        idempotency_key,request_hash)
                        SELECT %s,report_id,case_id,report_version,%s,%s,1,input_hash,knowledge_version,
                        policy_version,'ctx-sharing-visible',%s FROM reports WHERE report_id=%s""",
                        (uuid4(), actor, consent, 'd'*64, rep_id))
                    case_for_ctx = conn.execute('SELECT case_id FROM reports WHERE report_id=%s',
                                                (rep_id,)).fetchone()['case_id']
                    check(client.get(f'/v1/cases/{case_for_ctx}/reports/1',
                          headers=headers).status_code == 200,
                          'published report from sharing-enabled run is patient-visible')
                extra = send2('再分析一次', docs=[doc2])
                run3_id = extra['tool_events'][0]['run_id']
                check(run3_id != run2_id, 'new initiating turn creates a new run')
                snapshot3 = conn.execute('SELECT context_snapshot FROM analysis_runs WHERE run_id=%s',
                                         (run3_id,)).fetchone()['context_snapshot']
                check(snapshot3['chat']['turns'][-1]['text'] == '再分析一次' and
                      snapshot3['chat']['anchor_turn_id'] == extra['turn_id'],
                      'new anchor freezes a new conversation boundary')
            client.patch(c2 + '/report-context', headers=headers, json={'enabled': False}).raise_for_status()
            disabled = send2('关闭共享后再分析', docs=[doc2])
            run4_id = disabled['tool_events'][0]['run_id']
            with connection() as conn:
                conn.autocommit = True
                snapshot4 = conn.execute('SELECT context_snapshot FROM analysis_runs WHERE run_id=%s',
                                         (run4_id,)).fetchone()['context_snapshot']
                check(snapshot4['chat'] is None and snapshot4['case_user_context'] is None,
                      'disabled sharing excludes chat from newly created runs')
                late = claim_run(conn)
                check(late is not None and str(late['run_id']) == run3_id,
                      'run queued while sharing was on remains the worker candidate after withdrawal')
                with patch.dict(os.environ, {'LLM_API_KEY': ''}):
                    process_run(conn, late, Path(ctx_storage))
                late_row = conn.execute('SELECT status,error FROM analysis_runs WHERE run_id=%s',
                                        (run3_id,)).fetchone()
                check(late_row['status'] == 'failed' and
                      (late_row['error'] or {}).get('code') == 'REPORT_CONTEXT_UNAUTHORIZED',
                      'late worker result is rejected after sharing is withdrawn')
                # After version bump, the old sharing-enabled report is hidden.
                if rep_row:
                    check(client.get(f'/v1/cases/{case_for_ctx}/reports/1',
                          headers=headers).status_code == 404,
                          'sharing withdrawal hides an already-published report from the patient')
                    # Feedback is NOT blocked: the patient still has case access;
                    # sharing withdrawal hides visibility but doesn't revoke
                    # case-level authorization or invalidate historical feedback.
            check(client.get(c2, headers=headers).json()['conversation']['report_context_enabled'] is False,
                  'sharing stays off after the withdrawal')
            enabled_again = client.patch(c2 + '/report-context', headers=headers, json={'enabled': True})
            check(enabled_again.status_code == 200 and enabled_again.json()['report_context_version'] >= 3,
                  're-enabling sharing bumps the sharing version')
            check(client.get(c2, headers=headers).json()['conversation']['report_context_enabled'] is True,
                  'owner can re-enable sharing explicitly')
            api.app.dependency_overrides.pop(api.document_storage_root, None)

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
        direct={'request_id':str(uuid4()),'message':'直接启动材料分析','document_ids':[document_id]}
        with patch('services.api.app.conversation_agent.AgentModel',side_effect=AssertionError('queue must not call model')):
            queued=client.post(base+'/analyses',headers=headers,json=direct)
            replay=client.post(base+'/analyses',headers=headers,json=direct)
        check(queued.status_code==200 and replay.json()['turn_id']==queued.json()['turn_id'],
              'direct analysis submission is durable and idempotent without a chat model call')
        check(client.post(base+'/analyses',headers=other_headers,json=direct).status_code==404,
              'another actor cannot start analysis in a private conversation')
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
