"""PostgreSQL review queue and immutable decision writes for REQ-06."""

import json
from uuid import UUID, uuid4

from .contracts.core import Insight, ReviewCorrection, ReviewDecision, ReviewTask
from .repository import _to_report, request_digest
from .review_service import (REVIEWABLE_REPORT_ERRORS, checked_report_content,
                             corrected_insight_payload, corrected_report_payload)
from .report_context import report_sources


class ReviewAccessDenied(Exception): pass
class ReviewNotFound(Exception): pass
class StaleReview(Exception): pass


def _insight(row) -> Insight:
    return Insight(
        insight_id=row["insight_id"], case_id=row["case_id"], run_id=row["run_id"],
        category=row["category"], label=row["label"], severity=row["severity"],
        confidence=row["confidence"], confidence_method=row["confidence_method"],
        evidence_ids=row["evidence_ids"], rationale=row["rationale"],
        uncertainty=row["uncertainty"], suggested_action=row["suggested_action"],
        review_required=row["review_required"], review_status=row["review_status"],
        judgment_status=row["judgment_status"], rule_version=row["rule_version"],
        knowledge_refs=row["knowledge_refs"],
    )


def list_reviews(conn, *, actor_id: UUID, status: str, limit: int,
                 cursor: UUID | None = None) -> list[ReviewTask]:
    role = conn.execute("SELECT role FROM actors WHERE actor_id=%s AND active=true", (actor_id,)).fetchone()
    if not role or role["role"] != "medical_reviewer":
        raise ReviewAccessDenied()
    rows = conn.execute(
        """SELECT t.*,to_jsonb(i) AS insight_payload,to_jsonb(r) AS report_payload FROM review_tasks t
           LEFT JOIN insights i ON t.target_type='insight' AND i.insight_id=t.target_id
             AND i.case_id=t.case_id AND i.run_id=t.run_id
           LEFT JOIN reports r ON t.target_type='report' AND r.report_id=t.target_id
             AND r.case_id=t.case_id AND r.run_id=t.run_id
           JOIN cases c ON c.case_id=t.case_id
           JOIN actor_subject_access a ON a.subject_id=c.subject_id
             AND a.actor_id=%s AND a.can_read_case=true
           JOIN actors ac ON ac.actor_id=a.actor_id AND ac.active=true AND ac.role='medical_reviewer'
           JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
           JOIN consent_purposes p ON p.consent_id=co.consent_id
             AND p.purpose='case_guidance' AND p.status='active'
             AND (p.expires_at IS NULL OR p.expires_at>now())
           WHERE (i.insight_id IS NOT NULL OR r.report_id IS NOT NULL)
             AND t.status=%s AND (%s::uuid IS NULL OR t.review_id>%s::uuid)
           ORDER BY t.review_id LIMIT %s""", (actor_id, status, cursor, cursor, limit),
    ).fetchall()
    accessible=[]
    for row in rows:
        if row['target_type']=='report':
            try:
                report_sources(conn,row['case_id'],row['run_id'])
                from .report_memory import check_report_refs
                frozen=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE run_id=%s',(row['run_id'],)).fetchone()
                check_report_refs(conn,frozen,row['report_payload']['memory_refs'])
            except ValueError:
                continue
        accessible.append(row)
    return [ReviewTask(review_id=r["review_id"], case_id=r["case_id"], run_id=r["run_id"],
        target_type=r["target_type"], target_id=r["target_id"],
        target_version=r["target_version"], status=r["status"], reason=r["reason"],
        target=_insight(r['insight_payload']) if r['target_type']=='insight' else _to_report(r['report_payload']),
        created_at=r["created_at"]) for r in accessible]


def decide_review(conn, *, actor_id: UUID, review_id: UUID, expected_version: int,
                  decision: str, reason: str, corrections: list[ReviewCorrection],
                  idempotency_key: str | None = None) -> ReviewDecision:
    digest = request_digest({'review_id': str(review_id), 'expected_version': expected_version,
        'decision': decision, 'reason': reason,
        'corrections': [c.model_dump(mode='json') for c in corrections]})
    with conn.transaction():
        if idempotency_key:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                         (f'review:{actor_id}:{idempotency_key}',))
        scope = conn.execute("""SELECT t.case_id FROM review_tasks t JOIN cases c ON c.case_id=t.case_id
            JOIN actor_subject_access a ON a.subject_id=c.subject_id AND a.actor_id=%s AND a.can_read_case=true
            WHERE t.review_id=%s""", (actor_id,review_id)).fetchone()
        if not scope:
            raise ReviewNotFound()
        # Memory scope precedes case locks across submission, worker, review and release.
        if conn.execute("SELECT 1 FROM review_tasks WHERE review_id=%s AND target_type='report'",(review_id,)).fetchone():
            from .report_memory import lock_run
            target_run=conn.execute('SELECT run_id FROM review_tasks WHERE review_id=%s',(review_id,)).fetchone()
            lock_run(conn,scope['case_id'],target_run['run_id'])
        # Use the worker's case lock before row locks and version allocation.
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                     (f"case-report:{scope['case_id']}",))
        row = conn.execute(
            """SELECT t.*,ac.role AS actor_role,c.user_context FROM review_tasks t
               JOIN cases c ON c.case_id=t.case_id
               JOIN actor_subject_access a ON a.subject_id=c.subject_id
                 AND a.actor_id=%s AND a.can_read_case=true
               JOIN actors ac ON ac.actor_id=a.actor_id AND ac.active=true
               JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
               JOIN consent_purposes p ON p.consent_id=co.consent_id
                 AND p.purpose='case_guidance' AND p.status='active'
                 AND (p.expires_at IS NULL OR p.expires_at>now())
               WHERE t.review_id=%s FOR UPDATE OF t,c FOR SHARE OF ac,a,co,p""", (actor_id, review_id),
        ).fetchone()
        if not row:
            raise ReviewNotFound()
        if row["actor_role"] != "medical_reviewer":
            raise ReviewAccessDenied()
        if idempotency_key:
            old = conn.execute('SELECT * FROM review_decisions WHERE reviewer_id=%s AND idempotency_key=%s',
                               (actor_id, idempotency_key)).fetchone()
            if old:
                if old['request_hash'] != digest:
                    raise StaleReview()
                return ReviewDecision.model_validate({key: old[key] for key in ReviewDecision.model_fields})
        if row['target_type']=='report':
            if not idempotency_key:
                raise ValueError('Idempotency-Key required for report decisions')
            target = conn.execute('SELECT * FROM reports WHERE report_id=%s AND case_id=%s AND run_id=%s FOR UPDATE',
                                 (row['target_id'], row['case_id'], row['run_id'])).fetchone()
            current_version = target['report_version'] if target else None
        else:
            target = conn.execute('SELECT * FROM insights WHERE insight_id=%s AND case_id=%s AND run_id=%s FOR UPDATE',
                                 (row['target_id'], row['case_id'], row['run_id'])).fetchone()
            latest = conn.execute(
                'SELECT version,payload FROM insight_revisions WHERE insight_id=%s ORDER BY version DESC LIMIT 1',
                (row['target_id'],)).fetchone()
            current_version = latest['version'] if latest else 1
        if not target:
            raise ReviewNotFound()
        if row["status"] != "pending" or expected_version != current_version:
            raise StaleReview()
        if decision != "correct" and corrections:
            raise ValueError("corrections only allowed for correct decision")
        result_report_id = None
        if row['target_type']=='report':
            result_report_id = _decide_report(conn, row, target, decision, corrections)
        elif decision == "correct":
            current = Insight.model_validate(latest["payload"]) if latest else _insight(target)
            evidence = conn.execute(
                "SELECT evidence_id FROM evidence WHERE case_id=%s AND run_id=%s",
                (row["case_id"], row["run_id"]),
            ).fetchall()
            payload = corrected_insight_payload(current, corrections,
                                                {str(x["evidence_id"]) for x in evidence})
            conn.execute(
                "INSERT INTO insight_revisions (insight_id,version,payload,review_id) VALUES (%s,%s,%s::jsonb,%s)",
                (row["target_id"], current_version + 1, json.dumps(payload, ensure_ascii=False), review_id),
            )
            review_status = "corrected"
        else:
            review_status = "approved" if decision == "approve" else "rejected"
        if row['target_type']=='insight':
            conn.execute("UPDATE insights SET review_status=%s,review_required=false WHERE insight_id=%s",
                         (review_status, row["target_id"]))
        conn.execute("UPDATE review_tasks SET status='decided',decided_at=now() WHERE review_id=%s", (review_id,))
        decision_id = uuid4()
        result = conn.execute(
            """INSERT INTO review_decisions
               (decision_id,review_id,target_type,target_id,target_version,decision,reason,
                corrections,reviewer_id,result_report_id,idempotency_key,request_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)
               RETURNING decided_at""",
            (decision_id, review_id, row["target_type"], row["target_id"], current_version,
             decision, reason, json.dumps([c.model_dump(mode="json") for c in corrections], ensure_ascii=False),
             actor_id, result_report_id, idempotency_key, digest),
        ).fetchone()
    return ReviewDecision(decision_id=decision_id, review_id=review_id,
        target_type=row["target_type"], target_id=row["target_id"], target_version=current_version,
        decision=decision, reason=reason, corrections=corrections,
        reviewer_id=actor_id, decided_at=result["decided_at"], result_report_id=result_report_id)


def _run_structured_dates(conn, run_id) -> dict | None:
    """Normalized admission/discharge dates recorded by the run's reconcile stage."""
    row = conn.execute('SELECT stage_results FROM analysis_runs WHERE run_id=%s', (run_id,)).fetchone()
    return ((row or {}).get('stage_results') or {}).get('reconcile', {}).get('structured_dates')


def _decide_report(conn, task, target, decision, corrections):
    current = _to_report(target)
    latest = conn.execute('SELECT max(report_version) AS version FROM reports WHERE case_id=%s',
                          (task['case_id'],)).fetchone()['version']
    if current.status!='pending_review' or latest!=current.report_version:
        raise StaleReview()
    if decision=='reject':
        conn.execute("UPDATE reports SET status='rejected' WHERE report_id=%s", (current.report_id,))
        return None
    structured_dates = _run_structured_dates(conn, task['run_id'])
    evidence = {str(r['evidence_id']): r['text_value'] or '' for r in conn.execute(
        'SELECT evidence_id,text_value FROM evidence WHERE case_id=%s AND run_id=%s',
        (task['case_id'], task['run_id'])).fetchall()}
    sources = report_sources(conn,task['case_id'],task['run_id'],lock=True)
    from .report_memory import check_report_refs
    source_run=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE run_id=%s',(task['run_id'],)).fetchone()
    check_report_refs(conn,source_run,current.memory_refs,lock=True)
    if decision=='approve':
        if set(current.validation_errors)-REVIEWABLE_REPORT_ERRORS:
            raise ValueError('report has unresolved validation errors; correct or reject it')
        checked_report_content(current, [], evidence, sources, structured_dates=structured_dates)
        sections = [s.model_dump(mode='json') for s in current.sections]
        for section in sections:
            for claim in section['claims']:
                if claim['review_status']=='rejected':
                    raise ValueError('report contains rejected claims')
                if claim['review_status']=='pending':
                    claim['review_status']='approved'
        conn.execute("UPDATE reports SET status='ready',sections=%s::jsonb WHERE report_id=%s",
                     (json.dumps(sections, ensure_ascii=False), current.report_id))
        return None
    report_id = uuid4()
    payload = corrected_report_payload(current, corrections, evidence, sources, report_id, latest+1,
                                       structured_dates=structured_dates)
    conn.execute("""INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,actions,
        input_hash,model_id,prompt_version,knowledge_version,policy_version,memory_refs,consent_refs,
        validation_errors,review_parent_id) VALUES (%s,%s,%s,%s,'pending_review',%s::jsonb,%s::jsonb,
        %s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)""", (report_id,current.case_id,current.run_id,
        payload['report_version'],json.dumps(payload['sections'],ensure_ascii=False),
        json.dumps(payload['actions'],ensure_ascii=False),current.input_hash,current.model_id,
        current.prompt_version,current.knowledge_version,current.policy_version,
        json.dumps(current.memory_refs),json.dumps(payload['consent_refs']),
        json.dumps(payload['validation_errors']),current.report_id))
    conn.execute("UPDATE reports SET status='rejected' WHERE report_id=%s", (current.report_id,))
    conn.execute("""INSERT INTO review_tasks(review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
        VALUES (%s,%s,%s,'report',%s,%s,'pending','corrected_report_requires_review')""",
        (uuid4(),current.case_id,current.run_id,report_id,payload['report_version']))
    return report_id
