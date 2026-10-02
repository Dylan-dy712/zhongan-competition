"""Authorized APP pull notifications, client receipts and immutable care feedback."""

from uuid import uuid4

from .repository import get_report, request_digest
from .review_repository import ReviewAccessDenied, ReviewNotFound, StaleReview


def _patient_scope(conn,actor_id,case_id,*,lock=False):
    row=conn.execute("""SELECT c.subject_id,c.consent_id,co.version AS consent_version,ac.role
        FROM cases c JOIN actors ac ON ac.actor_id=%s AND ac.active=true
        JOIN actor_subject_access a ON a.actor_id=ac.actor_id AND a.subject_id=c.subject_id AND a.can_read_case=true
        JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE c.case_id=%s"""+(' FOR SHARE OF c,ac,a,co,p' if lock else ''),(actor_id,case_id)).fetchone()
    if not row:
        raise ReviewNotFound()
    if row['role']!='patient':
        raise ReviewAccessDenied()
    return row


def _current_notification_report(conn,actor_id,event):
    if event['status']=='cancelled':
        return None
    report=get_report(conn,actor_id=actor_id,case_id=event['case_id'],version=event['report_version'],patient_view=True)
    latest=conn.execute('SELECT max(report_version) AS version FROM reports WHERE case_id=%s',
                        (event['case_id'],)).fetchone()['version']
    return report if report and report.status=='published' and report.report_version==latest else None


def list_deliveries(conn,*,actor_id,case_id,limit=20):
    _patient_scope(conn,actor_id,case_id)
    rows=conn.execute("""SELECT o.*,rel.report_id,rel.report_version FROM care_outbox o
        JOIN report_releases rel ON rel.release_id=o.release_id AND rel.case_id=o.case_id
        WHERE o.case_id=%s AND o.status<>'cancelled' ORDER BY o.created_at DESC,o.outbox_id DESC LIMIT %s""",
        (case_id,limit)).fetchall()
    result=[]
    for event in rows:
        if not event or not _current_notification_report(conn,actor_id,event):
            continue
        receipt=conn.execute('SELECT state,receipt_version FROM delivery_receipts WHERE outbox_id=%s AND actor_id=%s ORDER BY receipt_version DESC LIMIT 1',
                             (event['outbox_id'],actor_id)).fetchone()
        result.append({key:event[key] for key in ('outbox_id','case_id','report_id','report_version','created_at')} | {
            'message':'您的关怀报告已更新，可以进入查看。','channel':'app',
            'receipt_state':receipt['state'] if receipt else 'pending',
            'receipt_version':receipt['receipt_version'] if receipt else 0})
    return result


def record_receipt(conn,*,actor_id,outbox_id,state,expected_version,idempotency_key):
    digest=request_digest({'outbox_id':str(outbox_id),'state':state,'expected_version':expected_version})
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'receipt:{actor_id}:{idempotency_key}',))
        scope=conn.execute('SELECT case_id FROM care_outbox WHERE outbox_id=%s',(outbox_id,)).fetchone()
        if not scope:
            raise ReviewNotFound()
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f"case-report:{scope['case_id']}",))
        _patient_scope(conn,actor_id,scope['case_id'],lock=True)
        event=conn.execute("""SELECT o.*,rel.report_id,rel.report_version FROM care_outbox o
            JOIN report_releases rel ON rel.release_id=o.release_id AND rel.case_id=o.case_id
            WHERE o.outbox_id=%s FOR UPDATE OF o""",(outbox_id,)).fetchone()
        if not event or not _current_notification_report(conn,actor_id,event):
            raise ReviewNotFound()
        old=conn.execute('SELECT * FROM delivery_receipts WHERE actor_id=%s AND idempotency_key=%s',
                         (actor_id,idempotency_key)).fetchone()
        if old:
            if old['request_hash']!=digest:
                raise StaleReview()
            return _receipt(old)
        current=conn.execute('SELECT state,receipt_version FROM delivery_receipts WHERE outbox_id=%s AND actor_id=%s ORDER BY receipt_version DESC LIMIT 1',
                             (outbox_id,actor_id)).fetchone()
        version=current['receipt_version'] if current else 0
        next_state='presented' if current is None else ('read' if current['state']=='presented' else None)
        if expected_version!=version or state!=next_state:
            raise StaleReview()
        _patient_scope(conn,actor_id,scope['case_id'],lock=True)
        row=conn.execute("""INSERT INTO delivery_receipts(receipt_id,outbox_id,actor_id,receipt_version,state,idempotency_key,request_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(uuid4(),outbox_id,actor_id,version+1,state,idempotency_key,digest)).fetchone()
        if state=='read':
            conn.execute("UPDATE care_outbox SET status='acknowledged' WHERE outbox_id=%s",(outbox_id,))
        return _receipt(row)


def _receipt(row):
    return {key:row[key] for key in ('receipt_id','outbox_id','receipt_version','state','created_at')}


def submit_feedback(conn,*,actor_id,report_id,report_version,action_id,type,text,idempotency_key):
    digest=request_digest({'report_id':str(report_id),'report_version':report_version,
                           'action_id':str(action_id) if action_id else None,'type':type,'text':text})
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'feedback:{actor_id}:{idempotency_key}',))
        target=conn.execute('SELECT case_id FROM reports WHERE report_id=%s AND report_version=%s',
                            (report_id,report_version)).fetchone()
        if not target:
            raise ReviewNotFound()
        case_id=target['case_id']
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'case-report:{case_id}',))
        scope=_patient_scope(conn,actor_id,case_id,lock=True)
        report=get_report(conn,actor_id=actor_id,case_id=case_id,version=report_version,patient_view=True)
        if not report or report.report_id!=report_id or (action_id and action_id not in {a.action_id for a in report.actions}):
            raise ReviewNotFound()
        old=conn.execute('SELECT * FROM care_feedback WHERE actor_id=%s AND idempotency_key=%s',
                         (actor_id,idempotency_key)).fetchone()
        if old:
            if old['request_hash']!=digest:
                raise StaleReview()
            return _feedback(old)
        _patient_scope(conn,actor_id,case_id,lock=True)
        row=conn.execute("""INSERT INTO care_feedback(feedback_id,actor_id,subject_id,case_id,report_id,report_version,
            action_id,type,text,consent_id,consent_version,triage_status,idempotency_key,request_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (uuid4(),actor_id,scope['subject_id'],case_id,report_id,report_version,action_id,type,text,scope['consent_id'],
             scope['consent_version'],'pending' if type in {'inaccurate','needs_help'} else 'not_required',idempotency_key,digest)).fetchone()
        return _feedback(row)


def _feedback(row):
    return {key:row[key] for key in ('feedback_id','report_id','report_version','action_id','type','text','triage_status','created_at')}


def list_feedback_triage(conn,*,actor_id,limit=20):
    actor=conn.execute('SELECT role FROM actors WHERE actor_id=%s AND active=true',(actor_id,)).fetchone()
    if not actor or actor['role'] not in {'medical_reviewer','customer_service'}:
        raise ReviewAccessDenied()
    rows=conn.execute("""SELECT f.* FROM care_feedback f JOIN cases c ON c.case_id=f.case_id
        JOIN actor_subject_access a ON a.subject_id=c.subject_id AND a.actor_id=%s AND a.can_read_case=true
        JOIN actors ac ON ac.actor_id=a.actor_id AND ac.active=true
        JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE f.triage_status='pending' AND f.consent_id=co.consent_id AND f.consent_version=co.version
          AND (ac.role='medical_reviewer' OR (ac.role='customer_service' AND f.type='needs_help'))
        ORDER BY f.created_at,f.feedback_id LIMIT %s""",(actor_id,limit)).fetchall()
    return [_feedback(row) for row in rows]
