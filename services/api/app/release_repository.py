"""Atomic report release; an outbox record is not proof of external delivery."""

from uuid import uuid4

from .repository import _to_report, request_digest, run_input_hash
from .report_context import context_sources
from .report_builder import POLICY_VERSION
from .fact_extractor import FIELD_TYPES
from .cost_breakdown import CostBreakdown, validate_cost_sources
from .review_repository import ReviewAccessDenied, ReviewNotFound, StaleReview
from .review_service import REVIEWABLE_REPORT_ERRORS, checked_report_content, check_report_knowledge


class ReleaseBlocked(ValueError): pass


def publish_report(conn, *, actor_id, case_id, version, expected_version, idempotency_key):
    digest = request_digest({'case_id':str(case_id),'version':version,'expected_version':expected_version})
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                     (f'release:{actor_id}:{idempotency_key}',))
        from .report_memory import lock_run, check_report_refs
        memory_run=conn.execute('SELECT run_id FROM reports WHERE case_id=%s AND report_version=%s',(case_id,version)).fetchone()
        if memory_run:
            lock_run(conn,case_id,memory_run['run_id'])
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'case-report:{case_id}',))
        scope = conn.execute("""SELECT c.*,ac.role,co.version AS consent_version FROM cases c
            JOIN actors ac ON ac.actor_id=%s AND ac.active=true
            JOIN actor_subject_access a ON a.actor_id=ac.actor_id AND a.subject_id=c.subject_id AND a.can_read_case=true
            JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
            JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
              AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
            WHERE c.case_id=%s FOR UPDATE OF c FOR SHARE OF ac,a,co,p""", (actor_id,case_id)).fetchone()
        if not scope:
            raise ReviewNotFound()
        if scope['role']!='medical_reviewer':
            raise ReviewAccessDenied()
        target = conn.execute('SELECT * FROM reports WHERE case_id=%s AND report_version=%s FOR UPDATE',
                              (case_id,version)).fetchone()
        if not target:
            raise ReviewNotFound()
        old = conn.execute('SELECT * FROM report_releases WHERE released_by=%s AND idempotency_key=%s',
                           (actor_id,idempotency_key)).fetchone()
        if old:
            if old['request_hash']!=digest:
                raise StaleReview()
            if old['consent_id']!=scope['consent_id'] or old['consent_version']!=scope['consent_version']:
                raise ReviewNotFound()
            replay_run=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE run_id=%s',(target['run_id'],)).fetchone()
            check_report_refs(conn,replay_run,target['memory_refs'],lock=True)
            return _release_result(conn,old)
        report = _to_report(target)
        latest = conn.execute('SELECT max(report_version) AS version FROM reports WHERE case_id=%s',
                              (case_id,)).fetchone()['version']
        if expected_version!=version or latest!=version or report.status!='ready':
            raise StaleReview()
        if report.policy_version!=POLICY_VERSION:
            raise ReleaseBlocked('report policy changed')
        if (len(report.consent_refs)!=1 or report.consent_refs[0].consent_id!=scope['consent_id'] or
            report.consent_refs[0].version!=scope['consent_version'] or report.consent_refs[0].purpose!='case_guidance'):
            raise ReleaseBlocked('report authorization snapshot is stale')
        if set(report.validation_errors)-REVIEWABLE_REPORT_ERRORS:
            raise ReleaseBlocked('unresolved report validation errors')
        if any(c.review_status in {'pending','rejected'} for s in report.sections for c in s.claims):
            raise ReleaseBlocked('report claims remain unresolved')
        needs_review = bool(report.memory_refs) or bool(report.validation_errors) or any(
            c.review_status in {'approved','corrected'} for s in report.sections for c in s.claims)
        if needs_review and not conn.execute("""SELECT 1 FROM review_decisions
            WHERE target_type='report' AND target_id=%s AND target_version=%s AND decision='approve'""",
            (report.report_id,version)).fetchone():
            raise ReleaseBlocked('report approval record missing')
        run = conn.execute('SELECT * FROM analysis_runs WHERE case_id=%s AND run_id=%s FOR SHARE',
                           (case_id,report.run_id)).fetchone()
        if not run or run['status']!='completed' or run['input_hash']!=report.input_hash:
            raise ReleaseBlocked('analysis is incomplete or input hash changed')
        check_report_refs(conn,run,report.memory_refs,lock=True)
        if any(run['stage_results'].get(stage,{}).get('status')!='completed' for stage in ('parse','extract')):
            raise ReleaseBlocked('required analysis stages are incomplete')
        documents = conn.execute('SELECT * FROM documents WHERE case_id=%s AND NOT EXISTS (SELECT 1 FROM document_replacements replacement WHERE replacement.old_document_id=documents.document_id) ORDER BY document_id FOR SHARE',
                                 (case_id,)).fetchall()
        snapshot = [{'document_id':str(d['document_id']),'document_version':d['document_version'],
                     'source_hash':d['source_hash']} for d in documents]
        if (not snapshot or any(d['status']!='parsed' for d in documents) or
            snapshot!=sorted(run['document_versions'],key=lambda d:(d['document_id'],d['document_version'])) or
            run_input_hash(snapshot,run['pipeline_version'],run.get('context_snapshot'))!=report.input_hash):
            raise ReleaseBlocked('current materials differ from reviewed input')
        if conn.execute("""SELECT 1 FROM analysis_runs WHERE case_id=%s AND run_id<>%s
            AND status IN ('queued','running') LIMIT 1""",(case_id,report.run_id)).fetchone():
            raise ReleaseBlocked('a newer analysis is still running')
        if conn.execute("""SELECT 1 FROM review_tasks WHERE case_id=%s AND run_id=%s AND status='pending' LIMIT 1""",
                        (case_id,report.run_id)).fetchone():
            raise ReleaseBlocked('required reviews remain pending')
        if conn.execute("""SELECT 1 FROM insights WHERE case_id=%s AND run_id=%s AND
            (review_required=true OR review_status='pending' OR (category='clinical' AND review_status='rejected')) LIMIT 1""",
            (case_id,report.run_id)).fetchone():
            raise ReleaseBlocked('insight review is incomplete or clinical content was rejected')
        facts = conn.execute('SELECT fact_type,status,assertion,evidence_ids,value FROM extracted_facts WHERE case_id=%s AND run_id=%s',
                             (case_id,report.run_id)).fetchall()
        if not set(FIELD_TYPES)<= {f['fact_type'] for f in facts}:
            raise ReleaseBlocked('required structured fields are missing from output')
        costs=[]
        for fact in facts:
            if fact['fact_type']=='cost_breakdown' and fact['value'] is not None:
                try:
                    cost=CostBreakdown.model_validate(fact['value'])
                except ValueError:
                    raise ReleaseBlocked('structured cost field is invalid') from None
                if set(fact['evidence_ids'])!={str(s.evidence_id) for f in cost.fields for s in f.sources}:
                    raise ReleaseBlocked('cost field source refs are incomplete')
                costs.append(cost)
                if any(field.amount.status=='conflict' for field in cost.fields):
                    raise ReleaseBlocked('cost component conflicts remain unresolved')
        if any(f['status']=='conflict' for f in facts):
            raise ReleaseBlocked('fact conflicts remain unresolved')
        uncertain = {str(ref) for f in facts if f['assertion'] in {'unknown','negated','historical','suspected'}
                     for ref in f['evidence_ids']}
        if any(uncertain.intersection(a.source_refs) for a in report.actions):
            raise ReleaseBlocked('action depends on uncertain or non-current facts')
        evidence_rows={str(e['evidence_id']):e for e in conn.execute(
            'SELECT evidence_id,text_value,document_id,document_version,page_index FROM evidence WHERE case_id=%s AND run_id=%s',
            (case_id,report.run_id)).fetchall()}
        evidence={key:row['text_value'] or '' for key,row in evidence_rows.items()}
        for cost in costs:
            try:
                validate_cost_sources(cost,evidence_rows)
            except ValueError:
                raise ReleaseBlocked('cost field is not supported by current source evidence') from None
        sources = context_sources(conn,run,lock=True)
        structured_dates = (run.get('stage_results') or {}).get('reconcile', {}).get('structured_dates')
        checked_sections, _, content_errors = checked_report_content(
            report,[],evidence,sources,structured_dates=structured_dates)
        # Recompute from actual content: stale/forged statuses and an empty saved error list
        # cannot turn a model label or paraphrase into an automatic approval.
        if (content_errors or any(c['review_status']=='pending' for s in checked_sections for c in s['claims'])) and not conn.execute("""SELECT 1 FROM review_decisions
            WHERE target_type='report' AND target_id=%s AND target_version=%s AND decision='approve'""",
            (report.report_id,version)).fetchone():
            raise ReleaseBlocked('report content requires an approval record')
        check_report_knowledge(report,'\n'.join(evidence.values()))
        # Expiry can pass while validation runs; row locks alone do not stop the clock.
        if not conn.execute("""SELECT 1 FROM consent_purposes WHERE consent_id=%s AND purpose='case_guidance'
            AND status='active' AND (expires_at IS NULL OR expires_at>clock_timestamp())""",(scope['consent_id'],)).fetchone():
            raise ReviewNotFound()
        release_id = uuid4()
        check_report_refs(conn,run,report.memory_refs,lock=True)  # Recheck clock-based expiry at commit.
        release = conn.execute("""INSERT INTO report_releases(release_id,report_id,case_id,report_version,released_by,
            consent_id,consent_version,input_hash,knowledge_version,policy_version,idempotency_key,request_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(release_id,report.report_id,
            case_id,version,actor_id,scope['consent_id'],scope['consent_version'],report.input_hash,
            report.knowledge_version,report.policy_version,idempotency_key,digest)).fetchone()
        conn.execute("UPDATE reports SET status='superseded' WHERE case_id=%s AND status='published'",(case_id,))
        conn.execute("UPDATE reports SET status='published' WHERE report_id=%s",(report.report_id,))
        conn.execute("""INSERT INTO care_outbox(outbox_id,release_id,case_id) VALUES (%s,%s,%s)""",
                     (uuid4(),release_id,case_id))
        return _release_result(conn,release)


def _release_result(conn, release):
    outbox = conn.execute('SELECT outbox_id,status FROM care_outbox WHERE release_id=%s',
                         (release['release_id'],)).fetchone()
    return {key:release[key] for key in ('release_id','report_id','case_id','report_version','created_at')} | {
        'outbox_id':outbox['outbox_id'],'delivery_status':outbox['status']}
