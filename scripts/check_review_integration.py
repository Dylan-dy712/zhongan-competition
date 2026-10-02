"""Transactional REQ-06 integration check; all synthetic rows are rolled back."""

import os
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from psycopg import sql
from fastapi.testclient import TestClient
from services.api.app import main as api
from services.api.app.report_builder import SECTION_TYPES

from services.api.app.repository import get_insights
from services.api.app.review_repository import (
    ReviewAccessDenied, ReviewNotFound, StaleReview, decide_review, list_reviews,
)
from services.api.app.repository import connect, token_digest


def main() -> None:
    reviewer, patient, subject, consent, case, run = [uuid4() for _ in range(6)]
    document, evidence, insight, review = [uuid4() for _ in range(4)]
    dsn = os.environ["ZHONGAN_DATABASE_URL"]
    schema = 'review_test_' + uuid4().hex
    admin = connect(dsn)
    admin.autocommit = True
    admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    conn = connect(dsn)
    conn.prepare_threshold = None
    def database():
        yield conn
    api.app.dependency_overrides[api.database] = database
    client = TestClient(api.app)
    reviewer_token, patient_token = uuid4().hex, uuid4().hex
    headers = {'Authorization': f'Bearer {reviewer_token}'}
    try:
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        for migration in sorted(Path('services/api/sql').glob('*.sql')):
            conn.execute(migration.read_text(encoding='utf-8'))
        conn.commit()
        conn.execute("INSERT INTO actors(actor_id,token_sha256,role) VALUES (%s,%s,'medical_reviewer'),(%s,%s,'patient')",
                     (reviewer, token_digest(reviewer_token), patient, token_digest(patient_token)))
        conn.execute("INSERT INTO actor_subject_access VALUES (%s,%s,false,true),(%s,%s,false,true)",
                     (reviewer, subject, patient, subject))
        conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'test',1)",
                     (consent, subject))
        conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())", (consent,))
        conn.execute("""INSERT INTO cases(case_id,subject_id,consent_id,created_by,source_ref,data_origin,idempotency_key,request_hash)
                        VALUES (%s,%s,%s,%s,'synthetic-review-check','synthetic','review-check',%s)""",
                     (case, subject, consent, patient, "c" * 64))
        conn.execute("""INSERT INTO documents(document_id,case_id,document_version,media_type,byte_size,source_hash,source_ref,storage_ref,status,policy_version)
                        VALUES (%s,%s,1,'text/plain',1,%s,'synthetic','/tmp/nonexistent','parsed','test')""",
                     (document, case, "d" * 64))
        conn.execute("""INSERT INTO analysis_runs(run_id,case_id,input_hash,schema_version,pipeline_version,document_versions,status,current_stage,execution_mode)
                        VALUES (%s,%s,%s,'0.1.0','text-parser-v1','[]','waiting_review','insights','live')""",
                     (run, case, "e" * 64))
        conn.execute("""INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,page_index,text_start,text_end,text_value,extraction_method,source_hash,parser_version)
                        VALUES (%s,%s,%s,%s,1,0,0,5,'合成证据','synthetic',%s,'test')""",
                     (evidence, run, case, document, "d" * 64))
        conn.execute("""INSERT INTO insights(insight_id,run_id,case_id,category,label,severity,evidence_ids,rationale,suggested_action,review_required,review_status,judgment_status,rule_version)
                        VALUES (%s,%s,%s,'clinical','CLIN_MEDICATION_CONTEXT_REVIEW','undetermined',%s::jsonb,'合成待核实线索','医学审核',true,'pending','candidate','test')""",
                     (insight, run, case, f'["{evidence}"]'))
        conn.execute("""INSERT INTO review_tasks(review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
                        VALUES (%s,%s,%s,'insight',%s,1,'pending','integration_check')""",
                     (review, case, run, insight))

        assert get_insights(conn, actor_id=patient, case_id=case, run_id=run) == []
        try:
            list_reviews(conn, actor_id=patient, status="pending", limit=10)
            raise AssertionError("patient accessed review queue")
        except ReviewAccessDenied:
            pass
        tasks = list_reviews(conn, actor_id=reviewer, status="pending", limit=10)
        assert len(tasks) == 1 and tasks[0].target_id == insight
        assert client.get('/v1/reviews', headers=headers).status_code == 200
        assert client.get('/v1/reviews', headers={'Authorization': f'Bearer {patient_token}'}).status_code == 403
        assert client.post(f'/v1/reviews/{review}/decision', headers={
            'Authorization': f'Bearer {patient_token}'}, json={
                'expected_version': 1, 'decision': 'approve', 'reason': 'forbidden'}).status_code == 403
        conn.execute('UPDATE actors SET active=false WHERE actor_id=%s', (reviewer,))
        assert client.get('/v1/reviews', headers=headers).status_code == 401
        conn.execute('UPDATE actors SET active=true WHERE actor_id=%s', (reviewer,))

        def assert_hidden():
            assert list_reviews(conn, actor_id=reviewer, status='pending', limit=10) == []
            assert client.get('/v1/reviews', headers=headers).json() == []
            response = client.post(f'/v1/reviews/{review}/decision', headers=headers, json={
                'expected_version': 1, 'decision': 'approve', 'reason': 'must be denied'})
            assert response.status_code == 404
            try:
                decide_review(conn, actor_id=reviewer, review_id=review, expected_version=1,
                              decision='approve', reason='must be denied', corrections=[])
                raise AssertionError('unauthorized review decision accepted')
            except ReviewNotFound:
                pass
            assert conn.execute('SELECT count(*) AS n FROM review_decisions').fetchone()['n'] == 0
            assert conn.execute('SELECT status FROM review_tasks WHERE review_id=%s', (review,)).fetchone()['status'] == 'pending'

        for status in ['revoked', 'expired']:
            conn.execute('UPDATE consent_purposes SET status=%s WHERE consent_id=%s', (status, consent))
            assert_hidden()
        conn.execute("UPDATE consent_purposes SET status='active',expires_at=now()-interval '1 minute' WHERE consent_id=%s", (consent,))
        assert_hidden()
        conn.execute('UPDATE consent_purposes SET expires_at=NULL,purpose=\'other_purpose\' WHERE consent_id=%s', (consent,))
        assert_hidden()
        conn.execute("UPDATE consent_purposes SET purpose='case_guidance' WHERE consent_id=%s", (consent,))
        conn.execute('UPDATE consents SET subject_id=%s WHERE consent_id=%s', (uuid4(), consent))
        assert_hidden()
        conn.execute('UPDATE consents SET subject_id=%s WHERE consent_id=%s', (subject, consent))
        conn.execute('UPDATE actor_subject_access SET can_read_case=false WHERE actor_id=%s', (reviewer,))
        assert_hidden()
        conn.execute('UPDATE actor_subject_access SET can_read_case=true WHERE actor_id=%s', (reviewer,))
        result = decide_review(conn, actor_id=reviewer, review_id=review,
                               expected_version=1, decision="approve",
                               reason="synthetic integration approval", corrections=[])
        assert result.decision == "approve"
        assert len(get_insights(conn, actor_id=patient, case_id=case, run_id=run)) == 1
        try:
            decide_review(conn, actor_id=reviewer, review_id=review,
                          expected_version=1, decision="approve",
                          reason="stale duplicate", corrections=[])
            raise AssertionError("stale decision was accepted")
        except StaleReview:
            pass
        report_id = uuid4()
        sections = [{'section_type': kind, 'claims': [{'claim_id': str(uuid4()),
            'text': '模型尚未核实的合成结论', 'claim_type': 'case_fact', 'evidence_refs': [str(evidence)],
            'knowledge_refs': [], 'source_refs': [], 'review_status': 'pending'}]} for kind in SECTION_TYPES]
        conn.execute("""INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,actions,
            input_hash,model_id,prompt_version,knowledge_version,policy_version,consent_refs,validation_errors)
            VALUES (%s,%s,%s,1,'pending_review',%s::jsonb,'[]',%s,'synthetic','test','knowledge:none',
            'report-safety-v2',%s::jsonb,'["UNSAFE_OR_EMPTY_ACTION"]')""",
            (report_id,case,run,json.dumps(sections,ensure_ascii=False),'e'*64,
             json.dumps([{'consent_id': str(consent), 'version': 1, 'purpose': 'case_guidance'}])))
        # Reapplying migration backfills existing pending reports without duplicating tasks.
        migration = Path('services/api/sql/012_report_reviews.sql').read_text(encoding='utf-8')
        conn.execute(migration)
        conn.execute(migration)
        response=client.get('/v1/reviews',headers=headers)
        report_tasks=[t for t in response.json() if t['target_type']=='report']
        assert response.status_code==200 and len(report_tasks)==1
        task_id=report_tasks[0]['review_id']
        assert report_tasks[0]['target']['report_id']==str(report_id)
        patient_headers={'Authorization': f'Bearer {patient_token}'}
        assert client.get(f'/v1/cases/{case}/reports/1',headers=patient_headers).status_code==404
        approve={'expected_version': 1, 'decision': 'approve', 'reason': '合成审批测试'}
        assert client.post(f'/v1/reviews/{task_id}/decision',headers=headers,json=approve).status_code==422
        report_headers={**headers,'Idempotency-Key':'report-correct-test'}
        assert client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=approve).status_code==422

        corrected=deepcopy(sections)
        for section in corrected:
            section['claims'][0]['text']='合成证据'
        corrections=[{'field_or_claim_id':'sections','replacement': corrected,
                      'source_refs':[str(evidence)],'reason':'逐条核对原始合成证据'},
                     {'field_or_claim_id':'actions','replacement':[{
                         'action_id': str(uuid4()), 'report_id': str(report_id), 'source_refs': [str(evidence)],
                         'owner_role':'patient', 'action_text':'合成证据', 'due_at':None, 'due_source':'unknown',
                         'status':'proposed', 'priority':1, 'rationale':'合成来源行动'}],
                      'source_refs':[str(evidence)],'reason':'保留有来源行动'}]
        body={'expected_version':1,'decision':'correct','reason':'纠正草稿','corrections':corrections}
        bad=deepcopy(body)
        bad['corrections'][0]['replacement'][0]['claims'][0]['evidence_refs'].append(str(uuid4()))
        assert client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=bad).status_code==422
        bad=deepcopy(body)
        bad['corrections'][0]['replacement'][0]['claims'][0]['text']='请自行停药'
        assert client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=bad).status_code==422
        assert conn.execute('SELECT count(*) AS n FROM reports').fetchone()['n']==1
        result=client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=body)
        assert result.status_code==200, result.text
        new_id=result.json()['result_report_id']
        retry=client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=body)
        assert retry.status_code==200 and retry.json()==result.json()
        different={**body,'reason':'changed payload'}
        assert client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=different).status_code==409
        old=conn.execute('SELECT status,sections FROM reports WHERE report_id=%s',(report_id,)).fetchone()
        assert old['status']=='rejected' and old['sections']==sections
        new=conn.execute('SELECT report_version,status,review_parent_id FROM reports WHERE report_id=%s',(new_id,)).fetchone()
        assert new['report_version']==2 and new['status']=='pending_review' and new['review_parent_id']==report_id
        actions=conn.execute('SELECT actions FROM reports WHERE report_id=%s',(new_id,)).fetchone()['actions']
        assert len(actions)==1 and actions[0]['report_id']==new_id and actions[0]['feedback_ref'] is None
        queue=client.get('/v1/reviews',headers=headers).json()
        new_task=next(t for t in queue if t['target_id']==new_id)
        approve_headers={**headers,'Idempotency-Key':'report-approve-test'}
        assert client.post(f'/v1/reviews/{new_task["review_id"]}/decision',headers=approve_headers,json=approve).status_code==409
        approval=client.post(f'/v1/reviews/{new_task["review_id"]}/decision',headers=approve_headers,
                             json={**approve,'expected_version':2})
        assert approval.status_code==200, approval.text
        ready=conn.execute('SELECT status,sections FROM reports WHERE report_id=%s',(new_id,)).fetchone()
        assert ready['status']=='ready' and all(c['review_status']!='pending' for s in ready['sections'] for c in s['claims'])
        assert client.get(f'/v1/cases/{case}/reports/2',headers=patient_headers).status_code==404
        rejected_report, reject_task = uuid4(), uuid4()
        conn.execute("""INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,actions,
            input_hash,model_id,prompt_version,knowledge_version,policy_version,consent_refs,validation_errors)
            SELECT %s,case_id,run_id,3,'pending_review',sections,'[]',input_hash,model_id,prompt_version,
            knowledge_version,policy_version,consent_refs,'[]' FROM reports WHERE report_id=%s""", (rejected_report,new_id))
        conn.execute("""INSERT INTO review_tasks(review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
            VALUES (%s,%s,%s,'report',%s,3,'pending','synthetic rejection')""", (reject_task,case,run,rejected_report))
        rejection=client.post(f'/v1/reviews/{reject_task}/decision',headers={**headers,'Idempotency-Key':'report-reject'},
                              json={'expected_version':3,'decision':'reject','reason':'驳回合成报告'})
        assert rejection.status_code==200
        assert conn.execute('SELECT status FROM reports WHERE report_id=%s',(rejected_report,)).fetchone()['status']=='rejected'
        conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s", (consent,))
        assert client.get('/v1/reviews?status=decided', headers=headers).json() == []
        assert client.post(f'/v1/reviews/{task_id}/decision',headers=report_headers,json=body).status_code==404
        print("REQ06_REVIEW_INTEGRATION_OK: live consent and roles; report queue, migration backfill, hard-error blocking, source/safety rejection, immutable correction, idempotent replay, stale versions, ready hidden from patient, revoked replay")
    finally:
        conn.rollback()
        conn.close()
        api.app.dependency_overrides.pop(api.database, None)
        admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        admin.close()


if __name__ == "__main__":
    main()
