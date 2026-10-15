"""Synthetic product-memory isolation, lifecycle and actual Semantix protocol checks."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import threading
import tempfile
from contextlib import contextmanager
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from services.api.app import main as api, accounts, conversation_repository as chats, memory_repository as store, memory_service
from services.api.app.contracts.memory import MemoryCandidateCreate, MemorySuggestion
from services.api.app.repository import connect


def answer(**extra):
    return {'content': json.dumps({'text': '【合成测试】收到你的补充。', 'evidence_refs': [], 'history_refs': [], **extra}, ensure_ascii=False)}


class MemoryContractTests(unittest.TestCase):
    def test_identity_injection_and_dynamic_scope_are_rejected(self):
        body = dict(kind='communication_preference',field_key='communication_style',content='合成原话',source_turn_id=uuid4(),scope='patient')
        for extra in ({'actor_id':str(uuid4())},{'subject_id':str(uuid4())},{'namespace':'global'},
                      {'kind':'confirmed_context','field_key':'medication','expires_at':None},
                      {'kind':'confirmed_context','field_key':'followup_time','expires_at':datetime.now(timezone.utc)+timedelta(days=1)}):
            with self.assertRaises(ValidationError):
                MemoryCandidateCreate(**{**body,**extra})
        with self.assertRaises(ValidationError):
            MemorySuggestion(kind='communication_preference',field_key='allergy',content='合成原话')

    def test_protocol_rejects_unknown_ids_instead_of_hydrating_returned_text(self):
        row={'memory_id':uuid4(),'version':1,'content':'合成背景'}
        def fake_run(command,**kwargs):
            request=json.loads(kwargs['input'])
            output={'protocol':memory_service.PROTOCOL,'request_id':request['request_id'],
                'upstream':memory_service.UPSTREAM,'retriever':'semantix-bm25',
                'hits':[{'id':'another-patient:1','score':1,'coverage':1}]}
            return subprocess.CompletedProcess(command,0,json.dumps(output).encode(),b'')
        with patch.object(subprocess,'run',side_effect=fake_run):
            with self.assertRaises(ValueError): memory_service.rank_documents('合成',[row])

    def test_real_semantix_chinese_retrieval(self):
        executable=Path(__file__).resolve().parents[1]/'output_dir/memory-ranker'/('semantix-ranker.exe' if os.name=='nt' else 'semantix-ranker')
        if not executable.exists(): self.skipTest('Build ranker with python -m scripts.build_memory_ranker')
        rows=[{'memory_id':uuid4(),'version':1,'content':'【合成】复查地点还未确定。'},
              {'memory_id':uuid4(),'version':1,'content':'【合成】希望回答简短。'}]
        with patch.dict(os.environ,{'ZHONGAN_MEMORY_RANKER':str(executable)}):
            hits=memory_service.rank_documents('复查地点',rows)
        self.assertEqual([row['memory_id'] for row in hits],[rows[0]['memory_id']])


@unittest.skipUnless(os.getenv('ZHONGAN_MEMORY_TEST_DATABASE_URL'),'Isolated memory test database not configured')
class MemoryDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn=os.environ['ZHONGAN_MEMORY_TEST_DATABASE_URL']
        cls.schema='memory_test_'+uuid4().hex
        with connect(cls.dsn) as conn: conn.execute(f'CREATE SCHEMA {cls.schema}')
        with cls.connection() as conn:
            for path in sorted((Path(__file__).resolve().parents[1]/'services/api/sql').glob('*.sql')):
                conn.execute(path.read_text(encoding='utf-8'))
        cls.counter=100

    @classmethod
    def tearDownClass(cls):
        with connect(cls.dsn) as conn: conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    @classmethod
    def connection(cls):
        conn=connect(cls.dsn);conn.prepare_threshold=None
        conn.execute(f'SET search_path TO {cls.schema}');conn.commit()
        return conn

    def setUp(self):
        with self.connection() as conn:conn.execute('DELETE FROM auth_attempts')  # Only this class\'s isolated schema.
        def database():
            with self.connection() as conn: yield conn
        self.overrides=api.app.dependency_overrides.copy()
        api.app.dependency_overrides[api.database]=database
        self.client=TestClient(api.app)
        type(self).counter+=2
        def register(number):
            result=self.client.post('/v1/auth/register',json={'username':f'1390000{number:04d}','password':'synthetic-password',
                'display_name':'Synthetic self','care_consent':True})
            self.assertEqual(result.status_code,201,result.text)
            headers={'Authorization':'Bearer '+result.json()['access_token']}
            person=self.client.get('/v1/me/members',headers=headers).json()[0]
            return headers,person['subject_id']
        self.headers,self.subject=register(self.counter)
        self.other_headers,self.other_subject=register(self.counter+1)
        self.client.patch('/v1/me/members/'+self.subject,headers=self.headers,json={'name':'Synthetic self','relationship':'self'})
        family=self.client.post('/v1/me/members',headers=self.headers,json={'name':'Synthetic parent','relationship':'parent'})
        self.assertEqual(family.status_code,201,family.text)
        self.family=family.json()['subject_id']
        care=self.client.post('/v1/me/consents?subject_id='+self.family,headers={**self.headers,'Idempotency-Key':uuid4().hex},json={'confirmation':True,'expected_version':0})
        self.assertEqual(care.status_code,200,care.text)
        self.enable(self.subject)
        self.enable(self.family)
        with self.connection() as conn:
            self.actor=conn.execute('SELECT actor_id FROM user_accounts WHERE subject_id=%s',(self.subject,)).fetchone()['actor_id']
        self.source=self.conversation(self.subject)
        self.set_conversation(self.source,False,True)
        self.target=self.conversation(self.subject)
        self.set_conversation(self.target,True,False)

    def tearDown(self):
        self.client.close()
        api.app.dependency_overrides.clear();api.app.dependency_overrides.update(self.overrides)

    def base(self,subject=None):return '/v1/me/members/'+(subject or self.subject)

    def enable(self,subject):
        path=self.base(subject)+'/memory-settings'
        current=self.client.get(path,headers=self.headers).json()
        result=self.client.patch(path,headers={**self.headers,'Idempotency-Key':uuid4().hex},json={'enabled':True,'expected_version':current['version']})
        self.assertEqual(result.status_code,200,result.text)

    def conversation(self,subject):
        result=self.client.post('/v1/conversations',headers=self.headers,json={'conversation_id':str(uuid4()),'subject_id':subject})
        self.assertEqual(result.status_code,201,result.text)
        self.assertFalse(result.json()['recall_enabled'])
        return result.json()['conversation_id']

    def set_conversation(self,conversation,read,export):
        path='/v1/conversations/'+conversation+'/memory-settings'
        current=self.client.get(path,headers=self.headers).json()
        result=self.client.patch(path,headers=self.headers,json={'read_enabled':read,'export_enabled':export,'expected_version':current['version']})
        self.assertEqual(result.status_code,200,result.text)

    def source_turn(self,text='【合成】希望先分步骤解释，暂时不要使用缩写。',conversation=None):
        with self.connection() as conn:
            turn=chats.begin_turn(conn,self.actor,UUID(conversation or self.source),uuid4(),text,[])
            chats.finish_turn(conn,self.actor,UUID(conversation or self.source),turn,answer={'text':'合成回答','evidence_refs':[],'history_refs':[]})
            return str(turn['turn_id'])

    def candidate(self,text=None,conversation=None,subject=None,**changes):
        text=text or '【合成】希望先分步骤解释，暂时不要使用缩写。'
        turn=self.source_turn(text,conversation)
        body={'source_turn_id':turn,'kind':'communication_preference','field_key':'communication_style','content':text,'scope':'patient',**changes}
        response=self.client.post(self.base(subject)+'/memory-candidates',headers=self.headers,json=body)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def confirm(self,candidate,**changes):
        response=self.client.post(self.base()+'/memory-candidates/'+candidate['candidate_id']+'/confirm',
            headers={**self.headers,'Idempotency-Key':uuid4().hex},json={'confirmation':True,'expected_version':candidate['version'],**changes})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def send(self,message='请按我偏好的沟通方式说一下',conversation=None,model=None):
        model=model or MagicMock();model.complete.return_value=answer()
        with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
            response=self.client.post('/v1/conversations/'+(conversation or self.target)+'/messages',headers=self.headers,
                json={'request_id':str(uuid4()),'message':message})
        return response,model

    def report_enabled(self, enabled=True):
        path=f'/v1/conversations/{self.target}/memory-settings'
        current=self.client.get(path,headers=self.headers).json()
        result=self.client.patch(path,headers=self.headers,json={'read_enabled':True,'export_enabled':False,
            'report_enabled':enabled,'expected_version':current['version']})
        self.assertEqual(result.status_code,200,result.text)

    @contextmanager
    def report_fixture(self, during_model=None):
        from services.api.app import worker
        from services.api.app.report_builder import SECTION_TYPES
        from services.api.app.report_memory import source_key
        saved=self.confirm(self.candidate(text='【合成】暂不确定是否存在青霉素过敏。',kind='confirmed_context',field_key='allergy'))
        self.report_enabled()
        with tempfile.TemporaryDirectory(prefix='synthetic-memory-report-') as directory:
            api.app.dependency_overrides[api.document_storage_root]=lambda:Path(directory)
            uploaded=self.client.post(f'/v1/conversations/{self.target}/documents',headers=self.headers,
                files={'file':('synthetic.txt','【合成】医疗总费用：120元'.encode(),'text/plain')})
            self.assertEqual(uploaded.status_code,201,uploaded.text)
            submitted=self.client.post(f'/v1/conversations/{self.target}/analyses',headers=self.headers,
                json={'request_id':str(uuid4()),'message':'【合成】请生成报告','document_ids':[uploaded.json()['document_id']]})
            self.assertEqual(submitted.status_code,200,submitted.text)
            run_id=UUID(submitted.json()['tool_events'][0]['run_id'])
            def model(*args, **kwargs):
                memory=kwargs['memory_context']
                self.assertEqual(memory['items'][0]['memory_id'],saved['memory_id'])
                if during_model:during_model(saved)
                fields={'status':'not_configured','raw_output':None,'repaired_output':None,
                    'candidates':{'candidates':[]},'personnel':[],'usage_metadata':{},'error_code':'SYNTHETIC_ONLY'}
                insights={'status':'not_configured','candidates':[],'raw_output':None,'usage_metadata':{},'error_code':'SYNTHETIC_ONLY'}
                item=memory['items'][0]
                draft={'sections':[{'section_type':kind,'claims':[{'text':item['content'],
                    'claim_type':'patient_statement','source_refs':[source_key(item)],'source_quote':item['content']}]} for kind in SECTION_TYPES],
                    'actions':[]}
                report={'status':'completed','draft':draft,'raw_output':draft,'repaired_output':None,'usage_metadata':{},'error_code':None}
                return fields,insights,report,'synthetic','memory-report-test',{}
            with self.connection() as conn:
                conn.autocommit=True
                claimed=worker.claim_run(conn)
                self.assertEqual(claimed['run_id'],run_id)
                with patch.object(worker,'analyze_models',side_effect=model):
                    worker.process_run(conn,claimed,Path(directory))
                run=conn.execute('SELECT * FROM analysis_runs WHERE run_id=%s',(run_id,)).fetchone()
                report=conn.execute('SELECT * FROM reports WHERE run_id=%s',(run_id,)).fetchone()
                yield conn,saved,run,report

    def approve_report(self,conn,report):
        from services.api.app.repository import token_digest
        from services.api.app.review_repository import decide_review
        reviewer=uuid4()
        conn.execute("INSERT INTO actors(actor_id,token_sha256,role) VALUES (%s,%s,'medical_reviewer')",(reviewer,token_digest(uuid4().hex)))
        conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)',(reviewer,self.subject))
        task=conn.execute("SELECT review_id FROM review_tasks WHERE target_type='report' AND target_id=%s",(report['report_id'],)).fetchone()
        decide_review(conn,actor_id=reviewer,review_id=task['review_id'],expected_version=1,
            decision='approve',reason='Synthetic source review only',corrections=[],idempotency_key=uuid4().hex)
        return reviewer

    def test_report_snapshot_requires_separate_permission_and_tracks_exact_versions(self):
        from services.api.app.report_context import capture_context,context_sources
        from services.api.app.report_memory import references
        saved=self.confirm(self.candidate())
        with self.connection() as conn:
            case=chats.require_conversation(conn,self.actor,UUID(self.target))['case_id']
            private=capture_context(conn,case,self.actor,UUID(self.target))
            self.assertFalse(references(private))
        self.report_enabled()
        with self.connection() as conn:
            snap=capture_context(conn,case,self.actor,UUID(self.target))
            self.assertEqual(references(snap),[f"memory:{saved['memory_id']}:v1"])
            self.assertTrue(context_sources(conn,{'case_id':case,'context_snapshot':snap}))
        self.report_enabled(False)
        self.report_enabled(True)
        with self.connection() as conn:
            with self.assertRaises(ValueError):context_sources(conn,{'case_id':case,'context_snapshot':snap})

    def test_report_worker_preserves_memory_refs_and_never_labels_them_medical_evidence(self):
        from services.api.app.material_report import get_material_report
        from services.api.app.report_memory import references
        with self.report_fixture() as (conn,saved,run,report):
            self.assertEqual(run['status'],'completed',run['error'])
            self.assertEqual(report['status'],'pending_review')
            self.assertEqual(report['memory_refs'],references(run['context_snapshot']))
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM evidence WHERE run_id=%s AND text_value LIKE %s',
                (run['run_id'],'%先分步骤解释%')).fetchone()['n'],0)
            material=get_material_report(conn,self.actor,UUID(self.target))
            self.assertEqual(material['status'],'available')
            self.assertFalse(any(section['items'] for section in material['sections']))

    def test_report_review_release_and_patient_reads_recheck_private_memory(self):
        from services.api.app.repository import get_report,get_analysis_run
        from services.api.app.release_repository import publish_report
        from services.api.app.report_memory import check_report_refs
        with self.report_fixture() as (conn,saved,run,report):
            reviewer=self.approve_report(conn,report)
            arguments=dict(actor_id=reviewer,case_id=run['case_id'],version=1,expected_version=1,idempotency_key=uuid4().hex)
            publish_report(conn,**arguments)
            self.assertIsNotNone(get_report(conn,actor_id=self.actor,case_id=run['case_id'],version=1))
            source_path=f"/v1/cases/{run['case_id']}/reports/1/memory-sources"
            sources=self.client.get(source_path,headers=self.headers)
            self.assertEqual(sources.status_code,200,sources.text)
            self.assertFalse(sources.json()['sources'][0]['medical_verification'])
            self.assertEqual(sources.json()['sources'][0]['memory_id'],saved['memory_id'])
            outsider=conn.execute('SELECT actor_id FROM user_accounts WHERE subject_id=%s',(self.other_subject,)).fetchone()['actor_id']
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,false,true)',(outsider,self.subject))
            self.assertIsNone(get_report(conn,actor_id=outsider,case_id=run['case_id'],version=1))
            self.assertEqual(self.client.get(source_path,headers=self.other_headers).status_code,404)
            conn.execute("UPDATE analysis_runs SET stage_results=jsonb_set(stage_results,'{guidance,reading_quality}',%s::jsonb) WHERE run_id=%s",
                (json.dumps({'explanation':'private synthetic memory assessment'}),run['run_id']))
            projected=get_analysis_run(conn,actor_id=outsider,run_id=run['run_id'])
            self.assertNotIn('private synthetic memory assessment',projected.model_dump_json())
            next_chat=self.client.post('/v1/conversations',headers=self.headers,json={'conversation_id':str(uuid4()),'case_id':str(run['case_id'])})
            self.assertEqual(next_chat.status_code,201,next_chat.text)
            detail=self.client.get('/v1/conversations/'+next_chat.json()['conversation_id'],headers=self.headers)
            self.assertEqual(detail.status_code,200,detail.text)
            self.assertEqual(detail.json()['report']['status'],'recall_disabled')
            self.assertIsNotNone(get_report(conn,actor_id=reviewer,case_id=run['case_id'],version=1))
            original=conn.execute('SELECT sections FROM reports WHERE report_id=%s',(report['report_id'],)).fetchone()['sections']
            store.revoke_memory(conn,self.actor,UUID(self.subject),UUID(saved['memory_id']),1)
            self.assertIsNone(get_report(conn,actor_id=self.actor,case_id=run['case_id'],version=1))
            self.assertEqual(self.client.get(source_path,headers=self.headers).status_code,404)
            with self.assertRaises(ValueError):publish_report(conn,**arguments)
            with self.assertRaises(ValueError):check_report_refs(conn,run,report['memory_refs'])
            self.assertEqual(conn.execute('SELECT sections FROM reports WHERE report_id=%s',(report['report_id'],)).fetchone()['sections'],original)

    def test_report_source_withdrawal_after_review_blocks_release(self):
        from services.api.app.release_repository import publish_report
        with self.report_fixture() as (conn,saved,run,report):
            reviewer=self.approve_report(conn,report)
            self.set_conversation(self.source,False,False)
            with self.assertRaises(ValueError):publish_report(conn,actor_id=reviewer,case_id=run['case_id'],version=1,expected_version=1,idempotency_key=uuid4().hex)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM report_releases WHERE case_id=%s',(run['case_id'],)).fetchone()['n'],0)

    def test_report_tool_registers_dependencies_even_when_chat_retrieval_has_no_hit(self):
        from services.api.app.release_repository import publish_report
        with self.report_fixture() as (conn,saved,run,report):
            reviewer=self.approve_report(conn,report)
            publish_report(conn,actor_id=reviewer,case_id=run['case_id'],version=1,expected_version=1,idempotency_key=uuid4().hex)
            model=MagicMock()
            calls=[]
            def complete(messages,**kwargs):
                if not calls:
                    self.assertFalse(any('"care_memory"' in (item.get('content') or '') for item in messages))
                    calls.append(True)
                    return {'content':None,'tool_calls':[{'id':'read-report','type':'function',
                        'function':{'name':'read_report','arguments':'{}'}}]}
                return answer()
            model.complete.side_effect=complete
            response,_=self.send('读取报告',model=model)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['answer']['memory_refs'][0]['memory_id'],saved['memory_id'])
            store.revoke_memory(conn,self.actor,UUID(self.subject),UUID(saved['memory_id']),1)
            turns=chats.get_turns(conn,self.actor,UUID(self.target))
            self.assertTrue(next(turn for turn in turns if str(turn['turn_id'])==response.json()['turn_id'])['answer']['memory_unavailable'])

    def test_report_generation_discards_output_after_memory_withdrawal(self):
        def revoke(saved):
            with self.connection() as conn:store.revoke_memory(conn,self.actor,UUID(self.subject),UUID(saved['memory_id']),1)
        with self.report_fixture(revoke) as (conn,saved,run,report):
            self.assertEqual(run['status'],'failed')
            self.assertIsNone(report)

    def test_report_expiry_and_forged_dependency_list_fail_closed(self):
        from services.api.app.report_memory import check_report_refs
        with self.report_fixture() as (conn,saved,run,report):
            with self.assertRaises(ValueError):check_report_refs(conn,run,[])
            with self.assertRaises(ValueError):check_report_refs(conn,run,['memory:'+str(uuid4())+':v1'])
            conn.execute("UPDATE care_memories SET expires_at=now()-interval '1 second' WHERE memory_id=%s",(saved['memory_id'],))
            with self.assertRaises(ValueError):self.approve_report(conn,report)

    def test_confirmed_memory_reused_after_reopen_and_not_visible_to_family_or_other_account(self):
        candidate=self.candidate()
        response,model=self.send()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'],[],'Unconfirmed candidates cannot be retrieved')
        saved=self.confirm(candidate)
        response,model=self.send()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'][0]['memory_id'],saved['memory_id'])
        context=next(json.loads(item['content'])['care_memory'] for item in model.complete.call_args.args[0] if '"care_memory"' in (item.get('content') or ''))
        self.assertEqual(context[0]['content'],candidate['content']);self.assertFalse(context[0]['medical_verification'])
        with self.connection() as conn:
            self.assertTrue(conn.execute('SELECT 1 FROM chat_memory_refs WHERE memory_id=%s',(saved['memory_id'],)).fetchone())
        family=self.conversation(self.family);self.set_conversation(family,True,False)
        response,model=self.send(conversation=family)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'],[])
        self.assertEqual(self.client.get(self.base()+'/memories',headers=self.other_headers).status_code,404)
        self.assertEqual(self.client.request('DELETE',self.base(self.family)+'/memories/'+saved['memory_id'],headers=self.headers,json={'expected_version':1}).status_code,404)

    def test_source_ownership_and_exact_user_text_required(self):
        turn=self.source_turn()
        body={'source_turn_id':turn,'kind':'communication_preference','field_key':'communication_style','content':'助手凭空补充','scope':'patient'}
        self.assertEqual(self.client.post(self.base()+'/memory-candidates',headers=self.headers,json=body).status_code,422)
        body['content']='【合成】希望先分步骤解释，暂时不要使用缩写。'
        self.assertEqual(self.client.post(self.base(self.family)+'/memory-candidates',headers=self.headers,json=body).status_code,404)
        self.assertEqual(self.client.post(self.base()+'/memory-candidates',headers=self.headers,json={**body,'actor_id':str(uuid4())}).status_code,422)

    def test_same_source_can_be_explicitly_reconfirmed_after_revocation(self):
        candidate=self.candidate()
        saved=self.confirm(candidate)
        response=self.client.request('DELETE',self.base()+'/memories/'+saved['memory_id'],headers=self.headers,json={'expected_version':1})
        self.assertEqual(response.status_code,200,response.text)
        body={key:candidate[key] for key in ('source_turn_id','kind','field_key','content','scope','expires_at')}
        fresh=self.client.post(self.base()+'/memory-candidates',headers=self.headers,json=body)
        self.assertEqual(fresh.status_code,201,fresh.text)
        self.assertNotEqual(fresh.json()['candidate_id'],candidate['candidate_id'])
        self.assertEqual(fresh.json()['status'],'pending')
        self.confirm(fresh.json())

    def test_revision_uses_new_source_and_stale_confirmation_is_rejected(self):
        old=self.confirm(self.candidate())
        updated=self.candidate(text='【合成更正】现在希望先给简短结论，再解释细节。')
        saved=self.confirm(updated,replaces_memory_id=old['memory_id'],replaces_version=1)
        self.assertEqual(saved['memory_id'],old['memory_id']);self.assertEqual(saved['version'],2)
        response,model=self.send()
        self.assertEqual(response.json()['answer']['memory_refs'][0]['version'],2)
        messages=json.dumps(model.complete.call_args.args[0],ensure_ascii=False)
        self.assertNotIn('暂时不要使用缩写',messages)
        response=self.client.post(self.base()+'/memory-candidates/'+updated['candidate_id']+'/confirm',headers={**self.headers,'Idempotency-Key':uuid4().hex},json={'confirmation':True,'expected_version':1})
        self.assertEqual(response.status_code,409)

    def test_revoke_masks_old_derived_answers_and_prevents_replay(self):
        saved=self.confirm(self.candidate());response,_=self.send()
        self.assertEqual(response.status_code,200,response.text)
        result=self.client.request('DELETE',self.base()+'/memories/'+saved['memory_id'],headers=self.headers,json={'expected_version':1})
        self.assertEqual(result.status_code,200,result.text)
        self.assertFalse(result.json()['physical_deletion'])
        turns=self.client.get('/v1/conversations/'+self.target+'/turns',headers=self.headers).json()
        self.assertTrue(turns[-1]['answer']['memory_unavailable'])
        response,model=self.send()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'],[])
        self.assertFalse(any('"care_memory"' in item.get('content','') for item in model.complete.call_args.args[0]))

    def test_source_disable_master_revoke_and_regrant_do_not_revive_memory(self):
        original=self.candidate()
        saved=self.confirm(original)
        self.set_conversation(self.source,False,False)
        response,_=self.send();self.assertEqual(response.json()['answer']['memory_refs'],[])
        self.set_conversation(self.source,False,True)
        response,_=self.send();self.assertEqual(response.json()['answer']['memory_refs'],[], 'Source re-enable must not revive revoked content')
        path=self.base()+'/memory-settings';state=self.client.get(path,headers=self.headers).json()
        response=self.client.patch(path,headers={**self.headers,'Idempotency-Key':uuid4().hex},json={'enabled':False,'expected_version':state['version']})
        self.assertEqual(response.status_code,200,response.text)
        self.enable(self.subject)
        rows=self.client.get(self.base()+'/memories',headers=self.headers).json()['memories']
        self.assertEqual(next(row for row in rows if row['memory_id']==saved['memory_id'])['status'],'revoked')
        response,_=self.send();self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'],[])
        body={key:original[key] for key in ('source_turn_id','kind','field_key','content','scope','expires_at')}
        candidate=self.client.post(self.base()+'/memory-candidates',headers=self.headers,json=body)
        self.assertEqual(candidate.status_code,201,candidate.text)
        self.assertNotEqual(candidate.json()['candidate_id'],original['candidate_id'])
        self.confirm(candidate.json())

    def test_case_scope_and_expiry_do_not_become_current_patient_facts(self):
        candidate=self.candidate(text='【合成】复查地点还未确定。',kind='confirmed_context',field_key='followup_location',scope='case',
            expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        saved=self.confirm(candidate)
        response,_=self.send(message='复查地点');self.assertEqual(response.json()['answer']['memory_refs'],[])
        self.set_conversation(self.source,True,True)
        response,_=self.send(message='复查地点',conversation=self.source)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'][0]['memory_id'],saved['memory_id'])
        with self.connection() as conn:conn.execute("UPDATE care_memories SET expires_at=now()-interval '1 second' WHERE memory_id=%s",(saved['memory_id'],))
        response,_=self.send(message='复查地点',conversation=self.source)
        self.assertEqual(response.json()['answer']['memory_refs'],[])

    def test_inflight_revocation_discards_output_and_does_not_persist_reference(self):
        saved=self.confirm(self.candidate())
        def complete(*args,**kwargs):
            with self.connection() as conn:store.revoke_memory(conn,self.actor,UUID(self.subject),UUID(saved['memory_id']),1)
            return answer()
        model=MagicMock();model.complete.side_effect=complete
        response,_=self.send(model=model)
        self.assertEqual(response.status_code,409,response.text)
        with self.connection() as conn:
            row=conn.execute('SELECT status,error_code FROM conversation_turns WHERE conversation_id=%s ORDER BY created_at DESC LIMIT 1',(self.target,)).fetchone()
            self.assertEqual(row,{'status':'failed','error_code':'MEMORY_CONTEXT_CHANGED'})

    def test_ranker_failure_degrades_current_chat_without_injecting_memory(self):
        self.confirm(self.candidate())
        with patch.dict(os.environ,{'ZHONGAN_MEMORY_RANKER':str(Path(__file__).resolve().parent/'missing-ranker')}):
            response,_=self.send()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['memory_refs'],[])
        self.assertEqual(response.json()['answer']['memory_status'],'retrieval_unavailable')

    def test_shared_patient_does_not_share_account_private_memory(self):
        self.confirm(self.candidate())
        with self.connection() as conn:
            other_actor=conn.execute('SELECT actor_id FROM user_accounts WHERE subject_id=%s',(self.other_subject,)).fetchone()['actor_id']
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)',(other_actor,self.subject))
            conn.execute("INSERT INTO account_members(actor_id,subject_id,name,relationship) VALUES (%s,%s,'Synthetic shared','other')",(other_actor,self.subject))
        response=self.client.get(self.base()+'/memories',headers=self.other_headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),{'memories':[],'candidates':[]})

    def test_automatic_suggestions_remain_unconfirmed_and_preserve_negation(self):
        text='【合成】我并没有确认过药物过敏。'
        model=MagicMock();model.complete.return_value=answer(memory_suggestions=[{'kind':'confirmed_context','field_key':'allergy','content':text}])
        with patch('services.api.app.conversation_agent.AgentModel',return_value=model):
            response=self.client.post('/v1/conversations/'+self.source+'/messages',headers=self.headers,
                json={'request_id':str(uuid4()),'message':text})
        self.assertEqual(response.status_code,200,response.text)
        items=self.client.get(self.base()+'/memories',headers=self.headers).json()
        self.assertEqual(items['memories'],[])
        self.assertEqual(items['candidates'][0]['content'],text)
        response,_=self.send(message='药物过敏')
        self.assertEqual(response.json()['answer']['memory_refs'],[])
        self.assertEqual(response.json()['answer']['memory_suggestions'],[])

    def test_raw_history_dependencies_do_not_reappear_after_source_withdrawal(self):
        self.source_turn('【合成】这次希望核对费用。')
        def model_response(messages,**kwargs):
            tool_messages=[message for message in messages if message['role']=='tool']
            if not tool_messages:
                return {'content':None,'tool_calls':[{'id':'history-call','type':'function','function':{'name':'search_history','arguments':'{"query":"费用"}'}}]}
            result=json.loads(tool_messages[-1]['content'])
            return answer(history_refs=[str(result['messages'][0]['turn_id'])])
        model=MagicMock();model.complete.side_effect=model_response
        response,_=self.send(message='上次关注什么',model=model)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['answer']['history_source_refs'])
        self.set_conversation(self.source,False,False)
        turns=self.client.get('/v1/conversations/'+self.target+'/turns',headers=self.headers).json()
        self.assertTrue(turns[-1]['answer']['memory_unavailable'])
        response,_=self.send();self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['answer']['history_source_refs'],[])

    def test_adding_unrelated_memory_does_not_hide_valid_past_answers(self):
        self.confirm(self.candidate())
        response,_=self.send();self.assertEqual(response.status_code,200,response.text)
        self.confirm(self.candidate(text='【合成】希望提前说明准备资料的步骤。',field_key='care_preference'))
        turns=self.client.get('/v1/conversations/'+self.target+'/turns',headers=self.headers).json()
        self.assertNotIn('memory_unavailable',turns[-1]['answer'])
        response,_=self.send()
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['answer']['memory_refs']),2)

    def test_multiple_clinical_self_reports_are_flagged_for_reconciliation(self):
        for text in ('【合成】之前没有确认过敏。','【合成】后来又补充了过敏情况，仍需核对。'):
            self.confirm(self.candidate(text=text,kind='confirmed_context',field_key='allergy'))
        response,model=self.send(message='过敏情况')
        self.assertEqual(response.status_code,200,response.text)
        context=next(json.loads(item['content'])['care_memory'] for item in model.complete.call_args.args[0] if '"care_memory"' in (item.get('content') or ''))
        self.assertTrue(context)
        self.assertTrue(all(item['requires_reconciliation'] and not item['medical_verification'] for item in context))

    def test_native_postgres_revocation_serializes_with_final_delivery(self):
        with self.connection() as conn:
            version=conn.execute('SELECT version() AS version').fetchone()['version']
        if 'wasm' in version.lower() or 'pglite' in version.lower():
            self.skipTest('Native PostgreSQL required for concurrent lock acceptance')
        saved=self.confirm(self.candidate())
        with self.connection() as first:
            state=store.settings(first,self.actor,UUID(self.subject))
            refs=[{'memory_id':saved['memory_id'],'version':1,'epoch':state['epoch']}]
            self.assertTrue(store.references_available(first,self.actor,UUID(self.target),refs,locked=True))
            started,finished=threading.Event(),threading.Event()
            errors=[]
            def revoke():
                try:
                    with self.connection() as second:
                        second.execute("SET statement_timeout='5s'")
                        started.set()
                        store.revoke_memory(second,self.actor,UUID(self.subject),UUID(saved['memory_id']),1)
                except Exception as exc:errors.append(type(exc).__name__)
                finally:finished.set()
            worker=threading.Thread(target=revoke)
            worker.start()
            try:
                self.assertTrue(started.wait(3))
                self.assertFalse(finished.wait(.2),'Revocation must serialize after the locked delivery snapshot')
            finally:
                first.commit()
                worker.join(8)
            self.assertTrue(finished.is_set());self.assertEqual(errors,[])
            self.assertFalse(store.references_available(first,self.actor,UUID(self.target),refs))

    def test_native_postgres_target_consent_revocation_serializes_with_final_delivery(self):
        with self.connection() as conn:
            version=conn.execute('SELECT version() AS version').fetchone()['version']
        if 'wasm' in version.lower() or 'pglite' in version.lower():
            self.skipTest('Native PostgreSQL required for concurrent lock acceptance')
        saved=self.confirm(self.candidate())
        # The destination has its own consent, so locking only the memory source
        # cannot accidentally satisfy this delivery/revocation race check.
        with self.connection() as conn:
            consent=uuid4()
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'account-care-v1',1)",
                         (consent,self.subject))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())",(consent,))
            conn.execute('UPDATE cases SET consent_id=%s WHERE case_id=(SELECT case_id FROM conversations WHERE conversation_id=%s)',
                         (consent,self.target))
        with self.connection() as first:
            state=store.settings(first,self.actor,UUID(self.subject))
            refs=[{'memory_id':saved['memory_id'],'version':1,'epoch':state['epoch']}]
            self.assertTrue(store.references_available(first,self.actor,UUID(self.target),refs,locked=True))
            started,finished=threading.Event(),threading.Event()
            errors=[]
            def revoke():
                try:
                    with self.connection() as second:
                        second.execute("SET statement_timeout='5s'")
                        started.set()
                        accounts.change_consent(second,self.actor,
                            accounts.ConsentChange(confirmation=False,expected_version=1),uuid4().hex,UUID(self.subject))
                except Exception as exc:errors.append(type(exc).__name__)
                finally:finished.set()
            worker=threading.Thread(target=revoke)
            worker.start()
            try:
                self.assertTrue(started.wait(3))
                self.assertFalse(finished.wait(.2),'Target consent withdrawal must wait for the locked delivery snapshot')
            finally:
                first.commit()
                worker.join(8)
            self.assertTrue(finished.is_set());self.assertEqual(errors,[])
            self.assertTrue(store.active_rows(first,self.actor,UUID(self.subject)))
            with self.assertRaises(store.AccessDenied):
                store.references_available(first,self.actor,UUID(self.target),refs)


if __name__=='__main__':unittest.main()
