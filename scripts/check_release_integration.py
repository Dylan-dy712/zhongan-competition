"""Real HTTP/SQL release gates in a disposable schema. Synthetic fixtures only."""

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from psycopg import sql
import psycopg

from services.api.app import main as api
from services.api.app.release_repository import publish_report
from services.api.app.fact_extractor import extract_facts
from services.api.app.cost_breakdown import cost_fact
from services.api.app.report_builder import SECTION_TYPES
from services.api.app.repository import connect, request_digest, token_digest
from services.api.app.knowledge_assembler import KnowledgeAssembler
from services.api.app.contracts.knowledge import DiseaseCode


def main():
    dsn=os.environ['ZHONGAN_DATABASE_URL']
    schema='release_test_'+uuid4().hex
    admin=connect(dsn)
    admin.autocommit=True
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    conn=connect(dsn)
    conn.prepare_threshold=None
    conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
    conn.commit()
    def database():
        yield conn
    api.app.dependency_overrides[api.database]=database
    client=TestClient(api.app)
    checks=[]
    def check(value,name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
    try:
        for migration in sorted(Path('services/api/sql').glob('*.sql')):
            conn.execute(migration.read_text(encoding='utf-8'))
        reviewer,patient,subject,consent,case,run,document,evidence,report=[uuid4() for _ in range(9)]
        reviewer_token,patient_token=uuid4().hex,uuid4().hex
        conn.execute("INSERT INTO actors(actor_id,token_sha256,role) VALUES (%s,%s,'medical_reviewer'),(%s,%s,'patient')",
                     (reviewer,token_digest(reviewer_token),patient,token_digest(patient_token)))
        conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true),(%s,%s,true,true)',
                     (reviewer,subject,patient,subject))
        conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'synthetic',1)",(consent,subject))
        conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())",(consent,))
        conn.execute("""INSERT INTO cases(case_id,subject_id,consent_id,created_by,source_ref,data_origin,idempotency_key,request_hash)
            VALUES (%s,%s,%s,%s,'release-synthetic','synthetic','fixture',%s)""",(case,subject,consent,patient,'a'*64))
        conn.execute("""INSERT INTO documents(document_id,case_id,media_type,byte_size,source_hash,source_ref,storage_ref,status,policy_version)
            VALUES (%s,%s,'text/plain',1,%s,'synthetic','synthetic-no-file','parsed','synthetic')""",(document,case,'b'*64))
        snapshot=[{'document_id':str(document),'document_version':1,'source_hash':'b'*64}]
        digest=request_digest({'documents':snapshot,'pipeline_version':'synthetic-release-test'})
        conn.execute("""INSERT INTO analysis_runs(run_id,case_id,input_hash,schema_version,pipeline_version,document_versions,
            status,current_stage,stage_results,execution_mode) VALUES (%s,%s,%s,'0.1.0','synthetic-release-test',%s::jsonb,
            'completed','validate','{"parse":{"status":"completed"},"extract":{"status":"completed"}}','mock')""",
            (run,case,digest,json.dumps(snapshot)))
        conn.execute("""INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,page_index,
            text_start,text_end,text_value,extraction_method,source_hash,parser_version)
            VALUES (%s,%s,%s,%s,1,0,0,12,'医疗总费用：120元','synthetic',%s,'synthetic')""",
            (evidence,run,case,document,'b'*64))
        for fact in extract_facts([{'evidence_id':evidence,'text':'医疗总费用：120元'}]):
            conn.execute("""INSERT INTO extracted_facts(fact_id,run_id,case_id,fact_type,value,raw_value,status,assertion,
                evidence_ids,confidence_score,confidence_method,unit,alternatives,missing_reason,extractor_version)
                VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s,%s)""",
                (fact['fact_id'],run,case,fact['fact_type'],json.dumps(fact['value']),fact['raw_value'],fact['status'],
                 fact['assertion'],json.dumps(fact['evidence_ids']),fact['confidence_score'],fact['confidence_method'],
                 fact['unit'],json.dumps(fact['alternatives']),fact['missing_reason'],fact['extractor_version']))
        sections=[{'section_type':kind,'claims':[{'claim_id':str(uuid4()),'text':'医疗总费用：120元',
            'claim_type':'case_fact','evidence_refs':[str(evidence)],'review_status':'not_required'}]} for kind in SECTION_TYPES]
        conn.execute("""INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,input_hash,model_id,
            prompt_version,knowledge_version,policy_version,consent_refs) VALUES (%s,%s,%s,1,'ready',%s::jsonb,%s,
            'synthetic','synthetic','knowledge:none','report-safety-v3',%s::jsonb)""",(report,case,run,json.dumps(sections),
            digest,json.dumps([{'consent_id':str(consent),'version':1,'purpose':'case_guidance'}])))
        conn.commit()
        conn.autocommit=True
        headers={'Authorization':f'Bearer {reviewer_token}','Idempotency-Key':'publish-one'}
        patient_headers={'Authorization':f'Bearer {patient_token}','Idempotency-Key':'patient-attempt'}
        endpoint=f'/v1/cases/{case}/reports/1/publish'
        def publish():
            return client.post(endpoint,headers=headers,json={'expected_version':1})
        def denied(expected,name):
            response=publish()
            check(response.status_code==expected,name+f' ({response.status_code})')
            check(conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==0 and
                  conn.execute('SELECT count(*) AS n FROM care_outbox').fetchone()['n']==0,name+' writes no release or outbox')
        check(client.post(endpoint,headers=patient_headers,json={'expected_version':1}).status_code==403,'patient cannot publish')
        check(client.get(f'/v1/cases/{case}/reports/1',headers=patient_headers).status_code==404,'ready is not patient-visible')
        conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
        denied(404,'revoked purpose blocks release')
        conn.execute("UPDATE consent_purposes SET status='active' WHERE consent_id=%s",(consent,))
        conn.execute('UPDATE consents SET version=2 WHERE consent_id=%s',(consent,))
        denied(422,'stale authorization snapshot blocks release')
        conn.execute('UPDATE consents SET version=1 WHERE consent_id=%s',(consent,))
        conn.execute("UPDATE reports SET memory_refs='[\"unverified-memory\"]' WHERE report_id=%s",(report,))
        denied(422,'unverified memory blocks release')
        conn.execute("UPDATE reports SET memory_refs='[]',knowledge_version='stale-build' WHERE report_id=%s",(report,))
        denied(422,'changed knowledge version blocks release')
        conn.execute("UPDATE reports SET knowledge_version='knowledge:none' WHERE report_id=%s",(report,))
        assembler=KnowledgeAssembler()
        entry=next(e for e in assembler.select(DiseaseCode.ty,patient_visible=False).allowed if e.status.value!='approved')
        unsafe_knowledge=deepcopy(sections)
        unsafe_knowledge[0]['claims'][0].update(claim_type='professional_explanation',review_status='approved',
                                              knowledge_refs=[entry.entry_id])
        conn.execute("UPDATE reports SET sections=%s::jsonb,knowledge_version=%s WHERE report_id=%s",
                     (json.dumps(unsafe_knowledge),assembler.knowledge_version,report))
        knowledge_task=uuid4()
        conn.execute("""INSERT INTO review_tasks(review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
            VALUES (%s,%s,%s,'report',%s,1,'decided','synthetic knowledge gate fixture')""",(knowledge_task,case,run,report))
        conn.execute("""INSERT INTO review_decisions(decision_id,review_id,target_type,target_id,target_version,decision,reason,reviewer_id)
            VALUES (%s,%s,'report',%s,1,'approve','report approval cannot approve knowledge',%s)""",(uuid4(),knowledge_task,report,reviewer))
        denied(422,'report approval cannot release unapproved knowledge')
        conn.execute('DELETE FROM review_decisions WHERE review_id=%s',(knowledge_task,))
        conn.execute('DELETE FROM review_tasks WHERE review_id=%s',(knowledge_task,))
        conn.execute("UPDATE reports SET sections=%s::jsonb,knowledge_version='knowledge:none' WHERE report_id=%s",
                     (json.dumps(sections),report))
        conn.execute("UPDATE analysis_runs SET status='failed' WHERE run_id=%s",(run,))
        denied(422,'failed analysis blocks release')
        conn.execute("UPDATE analysis_runs SET status='completed' WHERE run_id=%s",(run,))
        # A fabricated ready flag and empty stored errors must not bypass content revalidation.
        for claim_type,text,source_refs in [
            ('service_suggestion','现金支付等于个人自费',[]),
            ('to_confirm','需要核对这两个金额',[]),
            ('case_fact','医疗总费用：999元',[]),
            ('patient_statement','我担心恢复慢',['case:user_context'])]:
            conn.execute('UPDATE cases SET user_context=%s::jsonb WHERE case_id=%s',
                         (json.dumps({'concern':'我不担心恢复慢'}),case))
            unreviewed=deepcopy(sections)
            unreviewed[0]['claims'][0].update(claim_type=claim_type,text=text,source_refs=source_refs,
                                             evidence_refs=[str(evidence)] if claim_type=='case_fact' else [])
            conn.execute('UPDATE reports SET sections=%s::jsonb,validation_errors=\'[]\' WHERE report_id=%s',
                         (json.dumps(unreviewed),report))
            denied(422,claim_type+' requires actual approval despite forged ready/status/errors')
        conn.execute('UPDATE cases SET user_context=NULL WHERE case_id=%s',(case,))
        conn.execute('UPDATE reports SET sections=%s::jsonb WHERE report_id=%s',(json.dumps(sections),report))
        conn.execute('UPDATE documents SET document_version=2 WHERE document_id=%s',(document,))
        denied(422,'changed document version blocks release')
        conn.execute('UPDATE documents SET document_version=1 WHERE document_id=%s',(document,))
        conn.execute("""UPDATE extracted_facts SET status='conflict',value=NULL,evidence_ids='[]',
            alternatives=%s::jsonb WHERE run_id=%s AND fact_type='total_cost'""",(json.dumps([
                {'value':{'amount_minor':12000,'currency':'CNY'},'evidence_ids':[str(evidence)]},
                {'value':{'amount_minor':13000,'currency':'CNY'},'evidence_ids':[str(evidence)]}]),run))
        denied(422,'unresolved fact conflict blocks release')
        conn.execute("""UPDATE extracted_facts SET status='observed',value=%s::jsonb,evidence_ids=%s::jsonb,
            alternatives='[]' WHERE run_id=%s AND fact_type='total_cost'""",(json.dumps({'amount_minor':12000,'currency':'CNY'}),json.dumps([str(evidence)]),run))
        task=uuid4()
        conn.execute("""INSERT INTO review_tasks(review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
            VALUES (%s,%s,%s,'report',%s,1,'pending','synthetic review')""",(task,case,run,report))
        denied(422,'pending review blocks release')
        conn.execute("UPDATE review_tasks SET status='cancelled' WHERE review_id=%s",(task,))
        cost_source={'evidence_id':evidence,'document_id':document,'document_version':1,
                     'page_index':0,'text':'医疗总费用：120元'}
        expense=cost_fact([cost_source])
        conn.execute("""INSERT INTO extracted_facts(fact_id,run_id,case_id,fact_type,value,status,assertion,evidence_ids,
            derivation,alternatives,extractor_version) VALUES (%s,%s,%s,'cost_breakdown',%s::jsonb,'derived','present',
            %s::jsonb,%s::jsonb,'[]',%s)""",(expense['fact_id'],run,case,json.dumps(expense['value']),
            json.dumps(expense['evidence_ids']),json.dumps(expense['derivation']),expense['extractor_version']))
        original=deepcopy(expense['value'])
        altered=deepcopy(original)
        altered['fields'][0]['amount']['value']['amount_minor']=99900
        conn.execute("UPDATE extracted_facts SET value=%s::jsonb WHERE fact_id=%s",(json.dumps(altered),expense['fact_id']))
        denied(422,'forged composite cost amount blocks release')
        altered=deepcopy(original)
        altered['fields'][0]['amount']['value']['amount_minor']=12100
        altered['fields'][0]['sources'][0]['quote']='医疗总费用：121元'
        conn.execute("UPDATE extracted_facts SET value=%s::jsonb WHERE fact_id=%s",(json.dumps(altered),expense['fact_id']))
        denied(422,'valid-shaped cost quote absent from authoritative evidence blocks release')
        altered=deepcopy(original)
        foreign_doc=str(uuid4())
        altered['fields'][0]['document_id']=foreign_doc
        altered['fields'][0]['scope_ref']=f'{foreign_doc}@1:page:0'
        conn.execute("UPDATE extracted_facts SET value=%s::jsonb WHERE fact_id=%s",(json.dumps(altered),expense['fact_id']))
        denied(422,'cost field cannot cross its actual document scope')
        conn.execute("UPDATE extracted_facts SET value=%s::jsonb,evidence_ids='[]' WHERE fact_id=%s",
                     (json.dumps(original),expense['fact_id']))
        denied(422,'cost field cannot discard its source references')
        conflict=cost_fact([cost_source,{**cost_source,'text':'医疗总费用：130元'}])
        conn.execute("UPDATE extracted_facts SET value=%s::jsonb,evidence_ids=%s::jsonb WHERE fact_id=%s",
                     (json.dumps(conflict['value']),json.dumps(expense['evidence_ids']),expense['fact_id']))
        denied(422,'nested cost component conflict blocks release')
        check(publish().json()['message']=='cost component conflicts remain unresolved',
              'nested cost conflicts have an explicit release rejection reason')
        conn.execute("UPDATE extracted_facts SET value=%s::jsonb WHERE fact_id=%s",(json.dumps(original),expense['fact_id']))
        reviewed_sections=deepcopy(sections)
        reviewed_sections[4]['claims'].append({'claim_id':str(uuid4()),'text':'可以整理疑问，与客服逐项确认。',
            'claim_type':'service_suggestion','evidence_refs':[],'knowledge_refs':[],'source_refs':[],
            'review_status':'pending'})
        conn.execute("UPDATE reports SET status='pending_review',sections=%s::jsonb WHERE report_id=%s",
                     (json.dumps(reviewed_sections),report))
        service_review=task
        conn.execute("UPDATE review_tasks SET status='pending',reason='synthetic service suggestion review' WHERE review_id=%s",
                     (service_review,))
        approved=client.post(f'/v1/reviews/{service_review}/decision',
            headers={**headers,'Idempotency-Key':'approve-service-suggestion'},
            json={'expected_version':1,'decision':'approve','reason':'合成测试：核对用户服务建议'})
        check(approved.status_code==200,'service suggestion passes actual report approval API')
        check(conn.execute("SELECT count(*) AS n FROM review_decisions WHERE target_id=%s AND decision='approve'",
                           (report,)).fetchone()['n']==1,'reviewed report has an actual version-specific approval record')
        engine=conn.execute('SELECT version() AS version').fetchone()['version']
        sql_rollback='not_tested_pglite_protocol_limit'
        concurrency='not_tested_pglite_protocol_limit'
        if 'wasm32' not in engine:
            conn.execute("""CREATE FUNCTION release_fault() RETURNS trigger LANGUAGE plpgsql AS
                $$ BEGIN RAISE EXCEPTION 'synthetic outbox fault'; END $$""")
            conn.execute('CREATE TRIGGER outbox_fault BEFORE INSERT ON care_outbox FOR EACH ROW EXECUTE FUNCTION release_fault()')
            try:
                publish()
                raise AssertionError('outbox fault did not abort release')
            except psycopg.Error:
                pass
            check(conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==0 and
                  conn.execute('SELECT status FROM reports WHERE report_id=%s',(report,)).fetchone()['status']=='ready',
                  'outbox SQL failure rolls back release record and published status')
            conn.execute('DROP TRIGGER outbox_fault ON care_outbox')
            sql_rollback='passed'
        else:
            proxy=MagicMock(wraps=conn)
            def fault(query, params=None):
                if 'INSERT INTO care_outbox' in query:
                    raise RuntimeError('synthetic application failure before outbox insert')
                return conn.execute(query,params)
            proxy.execute.side_effect=fault
            with patch.object(api,'publish_report',side_effect=lambda _conn,**kw: publish_report(proxy,**kw)):
                try:
                    publish()
                    raise AssertionError('application fault did not abort release')
                except RuntimeError:
                    pass
            check(conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==0 and
                  conn.execute('SELECT status FROM reports WHERE report_id=%s',(report,)).fetchone()['status']=='ready',
                  'application failure before outbox insert rolls back release record and published status')
        if 'wasm32' not in engine:
            from scripts.check_release_concurrency import check_concurrency
            check_concurrency(conn,dsn,schema,reviewer=reviewer,patient=patient,case=case,consent=consent,
                              report=report,check=check)
            concurrency='passed'
            from scripts.check_quality_concurrency import check_quality_concurrency

            def quality_check(ok, msg):
                if not ok:
                    raise AssertionError(msg)

            check_quality_concurrency(conn, dsn, schema, reviewer=reviewer, subject=subject, check=quality_check)
            concurrency='passed+quality'
        released=publish()
        check(released.status_code==200,'validated report publishes through actual API')
        check(conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==1 and
              conn.execute('SELECT count(*) AS n FROM care_outbox').fetchone()['n']==1,'release and pending app outbox persist together')
        check(client.get(f'/v1/cases/{case}/reports/1',headers=patient_headers).status_code==200,'published report visible to authorized patient')
        check(publish().json()==released.json(),'same publish request replays same release')
        check(client.post(endpoint,headers=headers,json={'expected_version':2}).status_code==409,'changed publish payload conflicts')
        feed=client.get(f'/v1/cases/{case}/deliveries',headers=patient_headers)
        if feed.status_code!=200:
            raise AssertionError(f'APP feed HTTP {feed.status_code}: {feed.text}')
        check(len(feed.json())==1 and feed.json()[0]['receipt_state']=='pending',
              'APP pull feed returns eligible unread reminder')
        check('120' not in feed.json()[0]['message'] and '费用' not in feed.json()[0]['message'],
              'APP reminder contains no diagnosis or costs')
        event_id=feed.json()[0]['outbox_id']
        receipt_headers={**patient_headers,'Idempotency-Key':'presented-one'}
        receipt_url=f'/v1/deliveries/{event_id}/receipts'
        check(client.post(receipt_url,headers=receipt_headers,json={'state':'read','expected_version':0}).status_code==409,
              'receipt cannot skip presentation state')
        presented=client.post(receipt_url,headers=receipt_headers,json={'state':'presented','expected_version':0})
        check(presented.status_code==200 and presented.json()['receipt_version']==1,'APP presentation receipt is recorded')
        check(client.post(receipt_url,headers=receipt_headers,json={'state':'presented','expected_version':0}).json()==presented.json(),
              'presentation receipt replays without duplicate')
        check(client.post(receipt_url,headers=receipt_headers,json={'state':'read','expected_version':1}).status_code==409,
              'receipt idempotency key cannot change payload')
        read_headers={**patient_headers,'Idempotency-Key':'read-one'}
        read=client.post(receipt_url,headers=read_headers,json={'state':'read','expected_version':1})
        check(read.status_code==200 and conn.execute('SELECT status FROM care_outbox').fetchone()['status']=='acknowledged',
              'explicit read receipt acknowledges APP outbox')
        check(client.get(f'/v1/cases/{case}/deliveries',headers=patient_headers).json()[0]['receipt_state']=='read',
              'feed returns actual reader receipt state')
        feedback_body={'report_id':str(report),'report_version':1,'type':'inaccurate','text':'请帮我核对这段解释。'}
        feedback_headers={**patient_headers,'Idempotency-Key':'feedback-one'}
        check(client.post('/v1/feedback',headers=feedback_headers,json={**feedback_body,'action_id':str(uuid4())}).status_code==404,
              'feedback cannot refer to an unrelated action')
        feedback=client.post('/v1/feedback',headers=feedback_headers,json=feedback_body)
        check(feedback.status_code==201 and feedback.json()['triage_status']=='pending',
              'medical concern feedback enters actual pending triage')
        check(client.post('/v1/feedback',headers=feedback_headers,json=feedback_body).json()==feedback.json(),
              'feedback request replays same record')
        check(client.post('/v1/feedback',headers=feedback_headers,json={**feedback_body,'type':'helpful'}).status_code==409,
              'feedback idempotency key cannot change payload')
        triage=client.get('/v1/feedback/triage',headers=headers)
        check(triage.status_code==200 and len(triage.json())==1,'authorized reviewer sees pending feedback')
        check(client.get('/v1/feedback/triage',headers=patient_headers).status_code==403,'patient cannot read staff triage queue')
        outsider,proxy_patient,support=[uuid4() for _ in range(3)]
        outsider_token,proxy_token,support_token=[uuid4().hex for _ in range(3)]
        conn.execute("""INSERT INTO actors(actor_id,token_sha256,role) VALUES
            (%s,%s,'patient'),(%s,%s,'patient'),(%s,%s,'customer_service')""",
            (outsider,token_digest(outsider_token),proxy_patient,token_digest(proxy_token),support,token_digest(support_token)))
        outsider_headers={'Authorization':f'Bearer {outsider_token}','Idempotency-Key':'outsider'}
        counts=conn.execute('SELECT (SELECT count(*) FROM care_feedback) AS feedback,(SELECT count(*) FROM delivery_receipts) AS receipts').fetchone()
        check(client.get(f'/v1/cases/{case}/deliveries',headers=outsider_headers).status_code==404 and
              client.post(receipt_url,headers=outsider_headers,json={'state':'presented','expected_version':0}).status_code==404 and
              client.post('/v1/feedback',headers=outsider_headers,json=feedback_body).status_code==404,
              'unscoped patient cannot list reminders or submit receipts and feedback')
        check(conn.execute('SELECT (SELECT count(*) FROM care_feedback) AS feedback,(SELECT count(*) FROM delivery_receipts) AS receipts').fetchone()==counts,
              'unscoped patient writes no receipts or feedback')
        conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,false,true),(%s,%s,false,true)',
                     (proxy_patient,subject,support,subject))
        proxy_headers={'Authorization':f'Bearer {proxy_token}','Idempotency-Key':'proxy-presented'}
        proxy_feed=client.get(f'/v1/cases/{case}/deliveries',headers=proxy_headers).json()
        check(proxy_feed[0]['receipt_state']=='pending' and proxy_feed[0]['receipt_version']==0,
              'another authorized reader does not inherit first reader receipt')
        check(client.post(receipt_url,headers=proxy_headers,json={'state':'presented','expected_version':0}).status_code==200 and
              client.get(f'/v1/cases/{case}/deliveries',headers=patient_headers).json()[0]['receipt_state']=='read',
              'receipt versions are independent for each authorized reader')
        support_headers={'Authorization':f'Bearer {support_token}'}
        check(client.get('/v1/feedback/triage',headers=support_headers).json()==[],
              'customer service cannot read medical inaccuracy feedback')
        help_response=client.post('/v1/feedback',headers={**patient_headers,'Idempotency-Key':'needs-help'},
                                 json={**feedback_body,'type':'needs_help'})
        support_queue=client.get('/v1/feedback/triage',headers=support_headers).json()
        check(help_response.status_code==201 and len(support_queue)==1 and support_queue[0]['type']=='needs_help',
              'scoped customer service sees only help requests')
        conn.execute('UPDATE actor_subject_access SET can_read_case=false WHERE actor_id=%s',(support,))
        check(client.get('/v1/feedback/triage',headers=support_headers).json()==[],
              'staff scope removal hides triage records')
        newer=uuid4()
        conn.execute("""INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,input_hash,model_id,
            prompt_version,knowledge_version,policy_version,consent_refs)
            SELECT %s,case_id,run_id,2,'pending_review',sections,input_hash,model_id,prompt_version,knowledge_version,
                policy_version,consent_refs FROM reports WHERE report_id=%s""",(newer,report))
        check(client.get(f'/v1/cases/{case}/deliveries',headers=patient_headers).json()==[] and
              client.post(receipt_url,headers=read_headers,json={'state':'read','expected_version':1}).status_code==404,
              'a newer pending report hides old reminders and prevents old receipt replay')
        check(client.post('/v1/feedback',headers=feedback_headers,json=feedback_body).json()==feedback.json(),
              'feedback still refers to the explicitly selected accessible historical version')
        conn.execute('DELETE FROM reports WHERE report_id=%s',(newer,))
        conn.execute('UPDATE consents SET subject_id=%s WHERE consent_id=%s',(uuid4(),consent))
        check(client.get(f'/v1/cases/{case}/reports/1',headers=headers).status_code==404,
              'medical reviewer cannot read report using another subject consent')
        conn.execute('UPDATE consents SET subject_id=%s WHERE consent_id=%s',(subject,consent))
        conn.execute('UPDATE consents SET version=2 WHERE consent_id=%s',(consent,))
        check(client.get(f'/v1/cases/{case}/reports/1',headers=patient_headers).status_code==404,'new consent version cannot revive prior release')
        check(publish().status_code==404,'stale release replay is denied after consent version change')
        check(client.get(f'/v1/cases/{case}/deliveries',headers=patient_headers).json()==[],
              'old notification disappears after new consent version')
        check(client.post('/v1/feedback',headers=feedback_headers,json=feedback_body).status_code==404,
              'old feedback replay is denied after new consent version')
        conn.execute('UPDATE consents SET version=1 WHERE consent_id=%s',(consent,))
        conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
        check(client.get(f'/v1/cases/{case}/reports/1',headers=patient_headers).status_code==404 and
              publish().status_code==404,'revocation blocks published read and release replay')
        check(client.get(f'/v1/cases/{case}/deliveries',headers=patient_headers).status_code==404 and
              client.post(receipt_url,headers=read_headers,json={'state':'read','expected_version':1}).status_code==404,
              'revocation blocks feed and receipt replay')
        check(client.get('/v1/feedback/triage',headers=headers).json()==[],
              'revoked feedback is hidden from staff triage')
        print(json.dumps({'status':'passed','checks':checks,'count':len(checks),
                          'mode':'synthetic-fixtures/real-HTTP/SQL','engine':engine,'sql_error_rollback':sql_rollback,'concurrency':concurrency},ensure_ascii=False))
    finally:
        api.app.dependency_overrides.pop(api.database,None)
        conn.rollback()
        conn.close()
        admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


if __name__=='__main__':
    main()
