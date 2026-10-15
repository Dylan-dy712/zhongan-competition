"""Evidence binding, episode semantics and native/isolated PostgreSQL record flows."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from uuid import UUID,uuid4

from fastapi.testclient import TestClient
from services.api.app.main import app,database,document_storage_root
from services.api.app import medical_records as records
from services.api.app.medical_record_model import RecordDecision,validate_decision
from services.api.app.repository import connect
from services.api.app.worker import claim_run,process_run

def decision(relation='new_episode',target=None,related=None,left=None,right=None,current_text='',previous_text='',basis='distinct_event',diagnosis=None):
    return {'relation':relation,'target_case_id':str(target) if target else None,'related_case_id':str(related) if related else None,
        'confidence':0.98,'continuity_basis':basis,'reason':'依据本次资料中的就医日期与治疗经过整理。',
        'evidence_pairs':[{'current_ref':str(left),'previous_ref':str(right),'current_quote':current_text,'previous_quote':previous_text}] if left and right else [],
        'profile':{'diagnosis':{'value':diagnosis,'evidence_refs':[str(left)]} if diagnosis else None}}

class RecordModelTests(unittest.TestCase):
    def setUp(self):
        self.cid,self.pid,self.left,self.right=[uuid4() for _ in range(4)]
        self.current={'case_id':str(self.cid),'sources':[{'evidence_id':str(self.left),'text':'复诊记录：2026-09-20住院后复诊。诊断：疑似肺炎。'}]}
        self.previous={'case_id':str(self.pid),'profile':{'diagnosis':{'value':'疑似肺炎','evidence_refs':[str(self.right)]}},'sources':[{'evidence_id':str(self.right),'text':'2026-09-20入院，出院诊断：疑似肺炎。'}]}
    def checked(self,**changes):
        body=decision('follow_up',self.pid,left=self.left,right=self.right,current_text=self.current['sources'][0]['text'],previous_text=self.previous['sources'][0]['text'],basis='explicit_followup',diagnosis='疑似肺炎')
        body.update(changes)
        return validate_decision(RecordDecision(**body),self.current,[self.previous])
    def test_explicit_followup_has_matching_original_dates_and_qualified_profile(self):
        result=self.checked();self.assertTrue(result['automatic']);self.assertEqual(result['profile']['diagnosis']['value'],'疑似肺炎')
    def test_same_disease_and_confidence_alone_cannot_merge_episodes(self):
        self.assertFalse(self.checked(continuity_basis='same_condition_only')['automatic'])
        self.assertFalse(self.checked(confidence=0.89)['automatic'])
        self.current['sources'][0]['text']='肺炎复诊，未提供原治疗日期。'
        self.assertFalse(self.checked()['automatic'])
    def test_foreign_source_or_invented_quote_cannot_authorize_grouping(self):
        self.assertFalse(self.checked(target_case_id=str(uuid4()))['automatic'])
        result=self.checked(evidence_pairs=[{'current_ref':str(self.left),'previous_ref':str(self.right),'current_quote':'不存在的就医日期','previous_quote':self.previous['sources'][0]['text']}])
        self.assertFalse(result['automatic']);self.assertIsNone(result['target_case_id'])
    def test_profile_cannot_drop_uncertainty_or_copy_previous_patient_information(self):
        result=self.checked(profile={'diagnosis':{'value':'肺炎','evidence_refs':[str(self.left)]},'hospital':{'value':'某医院','evidence_refs':[str(self.right)]}})
        self.assertEqual(result['profile'],{})
    def test_recurrence_is_related_but_never_merged_and_mixed_stays_unassigned(self):
        result=self.checked(relation='new_episode',target_case_id=None,related_case_id=str(self.pid),continuity_basis='same_condition_only')
        self.assertFalse(result['automatic']);self.assertEqual(result['related_case_id'],str(self.pid));self.assertIsNone(result['target_case_id'])
        result=self.checked(relation='mixed');self.assertFalse(result['automatic']);self.assertIsNone(result['target_case_id'])
    def test_incompatible_current_diagnosis_prevents_same_date_accidental_merge(self):
        self.current['sources'][0]['text']='2026-09-20门诊，诊断：桡骨骨折。'
        self.previous['profile']={'diagnosis':{'value':'肺炎','evidence_refs':[str(self.right)]}}
        result=self.checked(relation='same_episode',continuity_basis='overlapping_dates_and_condition',profile={'diagnosis':{'value':'桡骨骨折','evidence_refs':[str(self.left)]}})
        self.assertFalse(result['automatic'])
        result=self.checked(relation='new_episode',target_case_id=None,related_case_id=str(self.pid),continuity_basis='distinct_event',profile={'diagnosis':{'value':'桡骨骨折','evidence_refs':[str(self.left)]}})
        self.assertIsNone(result['related_case_id'])

@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'),'Isolated PostgreSQL DSN not configured')
class MedicalRecordsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL'];self.schema='records_test_'+uuid4().hex
        with connect(self.dsn) as conn:conn.execute('CREATE SCHEMA '+self.schema)
        with self.connection() as conn:
            for path in sorted((Path(__file__).resolve().parents[1]/'services/api/sql').glob('*.sql')):conn.execute(path.read_text(encoding='utf-8'))
        def db():
            with self.connection() as conn:yield conn
        self.storage=tempfile.TemporaryDirectory()
        app.dependency_overrides[database]=db;app.dependency_overrides[document_storage_root]=lambda:Path(self.storage.name)
        self.client=TestClient(app);self.client.__enter__()
        body={'username':'13900000021','password':'1','display_name':'Synthetic record owner','care_consent':True}
        registration=self.client.post('/v1/auth/register',json=body);self.assertEqual(registration.status_code,201,registration.text)
        self.headers={'Authorization':'Bearer '+registration.json()['access_token']}
        self.subject=UUID(self.client.get('/v1/chat/subjects',headers=self.headers).json()[0]['subject_id'])
        other=self.client.post('/v1/auth/register',json={**body,'username':'13900000022'}).json()
        self.other={'Authorization':'Bearer '+other['access_token']}
    def tearDown(self):
        self.client.__exit__(None,None,None);app.dependency_overrides.pop(database,None);app.dependency_overrides.pop(document_storage_root,None);self.storage.cleanup()
        with connect(self.dsn) as conn:conn.execute('DROP SCHEMA '+self.schema+' CASCADE')
    def connection(self):
        conn=connect(self.dsn);conn.prepare_threshold=None;conn.execute('SET search_path TO '+self.schema);conn.commit();return conn
    def batch(self,text,headers=None,subject=None):
        headers=headers or self.headers;subject=subject or self.subject
        conversation=self.client.post('/v1/conversations',headers=headers,json={'conversation_id':str(uuid4()),'subject_id':str(subject),'recall_enabled':False}).json()
        response=self.client.post('/v1/conversations/'+conversation['conversation_id']+'/documents',headers=headers,files={'file':('synthetic.txt',text.encode(),'text/plain')})
        self.assertEqual(response.status_code,201,response.text);document=response.json()
        response=self.client.post('/v1/conversations/'+conversation['conversation_id']+'/analyses',headers=headers,json={'request_id':str(uuid4()),'message':'解读合成材料','document_ids':[document['document_id']]})
        self.assertEqual(response.status_code,200,response.text)
        with self.connection() as conn:
            run=conn.execute('SELECT * FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC LIMIT 1',(conversation['case_id'],)).fetchone()
            conn.execute("UPDATE analysis_runs SET status='completed',finished_at=now() WHERE run_id=%s",(run['run_id'],))
            ref=uuid4()
            conn.execute('''INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,page_index,text_start,text_end,text_value,extraction_method,source_hash,parser_version)
                VALUES (%s,%s,%s,%s,1,0,0,%s,%s,'controlled_text',%s,'synthetic-v1')''',(ref,run['run_id'],run['case_id'],document['document_id'],len(text),text,document['source_hash']))
            records.enqueue(conn,run['run_id'])
        return {'case':UUID(conversation['case_id']),'run':run['run_id'],'ref':ref,'text':text,'conversation':conversation['conversation_id']}
    def process(self,batch,body):
        client=MagicMock(model_id='synthetic-model');client._call.return_value=({'usage':{'total_tokens':3}},json.dumps(body,ensure_ascii=False))
        with self.connection() as conn:
            conn.autocommit=True;job=records.claim_job(conn);self.assertEqual(job['run_id'],batch['run'])
            with patch('services.api.app.medical_record_model.OpenAiCompatibleExtractor',return_value=client):records.process_job(conn,job)
        return client
    def listing(self):
        result=self.client.get('/v1/medical-records?subject_id='+str(self.subject),headers=self.headers)
        self.assertEqual(result.status_code,200,result.text);return result.json()
    def test_episode_enrichment_followup_recurrence_injury_and_manual_correction(self):
        first=self.batch('合成住院资料\n医院：合成医院\n入院日期：2026-09-20\n诊断：肺炎\n出院日期：2026-09-25')
        self.process(first,decision(left=first['ref'],diagnosis='肺炎'))
        supplement=self.batch('补充出院材料\n医院：合成医院\n入院日期：2026-09-20\n诊断：肺炎')
        self.process(supplement,decision('same_episode',first['case'],left=supplement['ref'],right=first['ref'],current_text=supplement['text'],previous_text=first['text'],basis='overlapping_dates_and_condition',diagnosis='肺炎'))
        follow=self.batch('门诊复诊\n2026-09-20住院治疗肺炎后的复诊\n本次就诊日期：2026-10-01\n诊断：肺炎恢复期')
        self.process(follow,decision('follow_up',first['case'],left=follow['ref'],right=first['ref'],current_text=follow['text'],previous_text=first['text'],basis='explicit_followup',diagnosis='肺炎恢复期'))
        listing=self.listing();self.assertEqual(len(listing['records']),1);self.assertEqual(len(listing['records'][0]['cases']),3)
        original_record=listing['records'][0]['record_id'];self.assertEqual(listing['records'][0]['document_count'],3)
        self.assertEqual(listing['records'][0]['portrait']['hospital']['value'],'合成医院')
        self.assertEqual(listing['records'][0]['portrait']['diagnosis']['value'],'肺炎恢复期')
        recurrence=self.batch('新一轮就医\n入院日期：2026-10-20\n诊断：肺炎')
        self.process(recurrence,decision('new_episode',related=first['case'],left=recurrence['ref'],right=first['ref'],current_text=recurrence['text'],previous_text=first['text'],basis='same_condition_only',diagnosis='肺炎'))
        injury=self.batch('门诊病历\n就诊日期：2026-10-22\n跌倒后新发外伤\n诊断：桡骨骨折')
        self.process(injury,decision(left=injury['ref'],diagnosis='桡骨骨折'))
        listing=self.listing();self.assertEqual(len(listing['records']),3)
        linked=next(r for r in listing['records'] if any(c['case_id']==str(recurrence['case']) for c in r['cases']))
        self.assertEqual(linked['related_records'][0]['record_id'],original_record)
        ambiguous=self.batch('肺炎复诊资料，没有提供就医日期。')
        self.process(ambiguous,decision('same_episode',first['case'],left=ambiguous['ref'],right=first['ref'],current_text=ambiguous['text'],previous_text=first['text'],basis='same_condition_only',diagnosis='肺炎'))
        listing=self.listing();batch=next(c for r in listing['records'] for c in r['cases'] if c['case_id']==str(ambiguous['case']))
        self.assertEqual(batch['organization_status'],'needs_confirmation');self.assertEqual(batch['proposed_record_id'],original_record)
        path='/v1/medical-records/cases/'+str(ambiguous['case'])
        body={'mode':'join','target_record_id':original_record,'expected_version':batch['version']}
        changed=self.client.patch(path,headers=self.headers,json=body);self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.client.patch(path,headers=self.headers,json=body).status_code,409)
        with self.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) n FROM cases').fetchone()['n'],6)
            self.assertEqual(conn.execute('SELECT count(*) n FROM evidence').fetchone()['n'],6)
            self.assertTrue(conn.execute('SELECT count(*) n FROM medical_record_audit').fetchone()['n']>=7)
        listing=self.listing();batch=next(c for r in listing['records'] for c in r['cases'] if c['case_id']==str(ambiguous['case']))
        changed=self.client.patch(path,headers=self.headers,json={'mode':'related','target_record_id':original_record,'expected_version':batch['version']})
        self.assertEqual(changed.status_code,200,changed.text)
        listing=self.listing();separate=next(r for r in listing['records'] if any(c['case_id']==str(ambiguous['case']) for c in r['cases']))
        self.assertNotEqual(separate['record_id'],original_record);self.assertEqual(separate['related_records'][0]['record_id'],original_record)
        # A new report version may enrich the portrait, but cannot undo a user's assignment.
        response=self.client.post('/v1/conversations/'+ambiguous['conversation']+'/analyses',headers=self.headers,
            json={'request_id':str(uuid4()),'message':'补充分析合成材料','document_ids':[],'force_new':True})
        self.assertEqual(response.status_code,200,response.text)
        with self.connection() as conn:
            run=conn.execute('SELECT * FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC LIMIT 1',(ambiguous['case'],)).fetchone()
            conn.execute("UPDATE analysis_runs SET status='completed',finished_at=now() WHERE run_id=%s",(run['run_id'],))
            document=conn.execute('SELECT * FROM documents WHERE case_id=%s',(ambiguous['case'],)).fetchone();ref=uuid4()
            conn.execute('''INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,page_index,text_start,text_end,text_value,extraction_method,source_hash,parser_version)
                VALUES (%s,%s,%s,%s,1,0,0,%s,%s,'controlled_text',%s,'synthetic-v1')''',(ref,run['run_id'],ambiguous['case'],document['document_id'],len(ambiguous['text']),ambiguous['text'],document['source_hash']))
            records.enqueue(conn,run['run_id'])
        updated={**ambiguous,'run':run['run_id'],'ref':ref}
        self.process(updated,decision(left=ref,diagnosis='肺炎'))
        unchanged=next(r for r in self.listing()['records'] if any(c['case_id']==str(ambiguous['case']) for c in r['cases']))
        self.assertEqual(unchanged['record_id'],separate['record_id']);self.assertEqual(unchanged['cases'][0]['assignment_source'],'user')
        # Repeated reads never generate a new analysis or grouping call.
        with patch('services.api.app.medical_record_model.OpenAiCompatibleExtractor') as model:
            self.listing();model.assert_not_called()
    def test_authorization_unavailable_model_stale_sources_and_job_replay(self):
        batch=self.batch('合成病历\n诊断：疑似肺炎\n就诊日期：2026-09-20')
        client=self.process(batch,decision(left=batch['ref'],diagnosis='疑似肺炎'))
        listing=self.listing();record=listing['records'][0];item=record['cases'][0]
        self.assertEqual(self.client.get('/v1/medical-records?subject_id='+str(self.subject),headers=self.other).status_code,404)
        self.assertEqual(self.client.patch('/v1/medical-records/cases/'+str(batch['case']),headers=self.other,json={'mode':'separate','expected_version':item['version']}).status_code,404)
        with self.connection() as conn:
            conn.autocommit=True;old=conn.execute('SELECT * FROM medical_record_jobs WHERE run_id=%s',(batch['run'],)).fetchone()
            with patch('services.api.app.medical_records.assess_record') as model:records.process_job(conn,old,assess=model);model.assert_not_called()
        # New uploads invalidate an old portrait until the matching analysis completes.
        response=self.client.post('/v1/conversations/'+batch['conversation']+'/documents',headers=self.headers,files={'file':('new.txt',b'new synthetic material','text/plain')})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.listing()['records'][0]['cases'][0]['profile'],{})
        other=self.batch('合成病历\n诊断：桡骨骨折')
        with self.connection() as conn:
            conn.autocommit=True;job=records.claim_job(conn)
            records.process_job(conn,job,assess=lambda *_:{'status':'unavailable','error_code':'RECORD_MODEL_FAILED','profile':{}})
            self.assertEqual(conn.execute('SELECT status FROM analysis_runs WHERE run_id=%s',(other['run'],)).fetchone()['status'],'completed')
            self.assertEqual(conn.execute('SELECT status FROM medical_record_jobs WHERE run_id=%s',(other['run'],)).fetchone()['status'],'failed')
        self.assertGreater(self.listing()['unorganized_count'],0)
        with self.connection() as conn:conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=(SELECT consent_id FROM cases WHERE case_id=%s)",(batch['case'],))
        listing=self.listing();self.assertEqual(listing['records'],[]);self.assertEqual(listing['processing_count'],0)
    def test_family_member_same_illness_cannot_be_used_as_a_grouping_target(self):
        self.client.patch('/v1/me/members/'+str(self.subject),headers=self.headers,json={'name':'Synthetic self','relationship':'self'})
        family=self.client.post('/v1/me/members',headers=self.headers,json={'name':'Synthetic parent','relationship':'parent'}).json()
        consent=self.client.post('/v1/me/consents?subject_id='+family['subject_id'],headers={**self.headers,'Idempotency-Key':'records-family-consent'},json={'confirmation':True,'expected_version':0})
        self.assertEqual(consent.status_code,200,consent.text)
        parent=self.batch('合成病历\n入院日期：2026-09-20\n诊断：肺炎',subject=UUID(family['subject_id']))
        self.process(parent,decision(left=parent['ref'],diagnosis='肺炎'))
        family_records=self.client.get('/v1/medical-records?subject_id='+family['subject_id'],headers=self.headers).json()
        own=self.batch('合成病历\n入院日期：2026-09-20\n诊断：肺炎')
        self.process(own,decision('same_episode',parent['case'],left=own['ref'],right=parent['ref'],current_text=own['text'],previous_text=parent['text'],basis='overlapping_dates_and_condition',diagnosis='肺炎'))
        listing=self.listing();self.assertEqual(len(listing['records']),1);self.assertIsNone(listing['records'][0]['cases'][0]['proposed_record_id'])
        item=listing['records'][0]['cases'][0]
        response=self.client.patch('/v1/medical-records/cases/'+str(own['case']),headers=self.headers,json={'mode':'join','target_record_id':family_records['records'][0]['record_id'],'expected_version':item['version']})
        self.assertEqual(response.status_code,404)
    def test_historical_root_organization_keeps_its_supplements_together(self):
        first=self.batch('合成住院病历\n入院日期：2026-09-20\n诊断：肺炎')
        self.process(first,decision(left=first['ref'],diagnosis='肺炎'))
        legacy=self.batch('合成旧资料\n入院日期：2026-09-20\n诊断：肺炎')
        with self.connection() as conn:conn.execute('DELETE FROM medical_record_jobs WHERE run_id=%s',(legacy['run'],))
        supplement=self.batch('合成补充资料\n入院日期：2026-09-20\n诊断：肺炎')
        self.process(supplement,decision('same_episode',legacy['case'],left=supplement['ref'],right=legacy['ref'],current_text=supplement['text'],previous_text=legacy['text'],basis='overlapping_dates_and_condition',diagnosis='肺炎'))
        self.assertEqual(len(self.listing()['records']),2)
        response=self.client.post('/v1/medical-records/organize',headers=self.headers,json={'subject_id':str(self.subject)})
        self.assertEqual(response.status_code,202,response.text)
        self.process(legacy,decision('same_episode',first['case'],left=legacy['ref'],right=first['ref'],current_text=legacy['text'],previous_text=first['text'],basis='overlapping_dates_and_condition',diagnosis='肺炎'))
        listing=self.listing();self.assertEqual(len(listing['records']),1);self.assertEqual(len(listing['records'][0]['cases']),3)
    def test_organization_queue_failure_cannot_roll_back_the_analysis(self):
        batch=self.batch('合成文本病历\n就诊日期：2026-09-20\n诊断：肺炎')
        with self.connection() as conn:
            conn.execute('DELETE FROM medical_record_jobs WHERE run_id=%s',(batch['run'],))
            conn.execute("UPDATE analysis_runs SET status='queued',finished_at=NULL WHERE run_id=%s",(batch['run'],))
        with self.connection() as conn:
            conn.autocommit=True;run=claim_run(conn)
            with patch.dict(os.environ,{'LLM_API_KEY':''}),patch('services.api.app.worker.medical_records.enqueue',side_effect=RuntimeError('synthetic queue unavailable')):
                process_run(conn,run,Path(self.storage.name))
            self.assertIn(conn.execute('SELECT status FROM analysis_runs WHERE run_id=%s',(batch['run'],)).fetchone()['status'],('completed','waiting_review'))
            self.assertEqual(conn.execute('SELECT count(*) n FROM reports WHERE run_id=%s',(batch['run'],)).fetchone()['n'],1)
    def test_group_with_user_confirmed_batch_requires_confirmation_before_auto_merge(self):
        first=self.batch('合成住院资料\n入院日期：2026-09-20\n诊断：肺炎');self.process(first,decision(left=first['ref'],diagnosis='肺炎'))
        legacy=self.batch('合成历史资料\n入院日期：2026-09-20\n诊断：肺炎')
        with self.connection() as conn:conn.execute('DELETE FROM medical_record_jobs WHERE run_id=%s',(legacy['run'],))
        supplement=self.batch('合成补充材料\n入院日期：2026-09-20\n诊断：肺炎')
        self.process(supplement,decision('same_episode',legacy['case'],left=supplement['ref'],right=legacy['ref'],current_text=supplement['text'],previous_text=legacy['text'],basis='overlapping_dates_and_condition',diagnosis='肺炎'))
        listing=self.listing();group=next(r for r in listing['records'] if any(c['case_id']==str(legacy['case']) for c in r['cases']));batch=next(c for c in group['cases'] if c['case_id']==str(supplement['case']))
        response=self.client.patch('/v1/medical-records/cases/'+str(supplement['case']),headers=self.headers,json={'mode':'join','target_record_id':group['record_id'],'expected_version':batch['version']})
        self.assertEqual(response.status_code,200,response.text)
        self.client.post('/v1/medical-records/organize',headers=self.headers,json={'subject_id':str(self.subject)})
        self.process(legacy,decision('same_episode',first['case'],left=legacy['ref'],right=first['ref'],current_text=legacy['text'],previous_text=first['text'],basis='overlapping_dates_and_condition',diagnosis='肺炎'))
        listing=self.listing();self.assertEqual(len(listing['records']),2)
        unchanged=next(r for r in listing['records'] if r['record_id']==group['record_id']);self.assertEqual(len(unchanged['cases']),2)
        self.assertEqual(next(c for c in unchanged['cases'] if c['case_id']==str(legacy['case']))['organization_status'],'needs_confirmation')

if __name__=='__main__':unittest.main()
