"""Automatically checked material report, separate from clinical report release.

Pending clinical prose and actions never cross this boundary. A version is a
deterministic projection of one report/run and its checked source evidence.
Every read rechecks ownership, consent, context and current document versions.
"""
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from .conversation_repository import require_conversation
from .report_builder import SECTION_TYPES, POLICY_VERSION, _unsafe, validate_and_complete
from .report_context import context_sources
from .repository import run_input_hash

MATERIAL_POLICY = 'material-report-v1'


def build_material_sections(report, evidence, sources, structured_dates=None):
    checked, _, _ = validate_and_complete(report, evidence, set(), sources, structured_dates)
    sections = []
    for section in checked:
        items, seen = [], set()
        pending = 0
        for claim in section.claims:
            if claim.review_status == 'not_required' and claim.claim_type in {'case_fact', 'patient_statement'}:
                items.append({'text': claim.text, 'kind': 'checked',
                              'evidence_refs': [str(x) for x in claim.evidence_refs]})
            else:
                pending += 1
                # Preserve qualifiers by displaying the whole source span, never a
                # model's unverified paraphrase. Professional advice stays withheld.
                if claim.claim_type != 'case_fact':
                    continue
                for ref in claim.evidence_refs:
                    key = str(ref)
                    quote = evidence.get(key, '')
                    if quote and key not in seen and not _unsafe(quote):
                        seen.add(key)
                        items.append({'text': quote, 'kind': 'source', 'evidence_refs': [key]})
        sections.append({'section_type': section.section_type, 'items': items,
                         'pending_count': pending})
    return sections


def get_material_report(conn, actor_id, conversation_id):
    conversation = require_conversation(conn, actor_id, conversation_id)
    case_id = conversation['case_id']
    run = conn.execute('SELECT * FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC,run_id DESC LIMIT 1',
                       (case_id,)).fetchone()
    if not run:
        return {'status': 'not_started'}
    if run['status'] in {'queued', 'running', 'failed', 'cancelled'}:
        return {'status': run['status'], 'run_id': str(run['run_id'])}
    report = conn.execute('SELECT * FROM reports WHERE case_id=%s AND run_id=%s ORDER BY report_version DESC LIMIT 1',
                          (case_id, run['run_id'])).fetchone()
    if not report:
        return {'status': 'not_generated', 'run_id': str(run['run_id'])}
    if report['status'] in {'rejected', 'invalidated'}:
        return {'status': 'outdated'}
    model = conn.execute("SELECT status FROM model_extractions WHERE run_id=%s AND prompt_version LIKE 'six-section-care-report%%' ORDER BY created_at DESC LIMIT 1",
                         (run['run_id'],)).fetchone()
    if not model or model['status'] != 'completed':
        return {'status': 'failed', 'run_id': str(run['run_id']), 'reason': 'REPORT_MODEL_FAILED'}
    consent = conn.execute('SELECT c.consent_id,co.version FROM cases c JOIN consents co ON co.consent_id=c.consent_id WHERE c.case_id=%s',
                           (case_id,)).fetchone()
    refs = report['consent_refs']
    if (report['policy_version'] != POLICY_VERSION or report['memory_refs'] or len(refs) != 1
            or refs[0]['consent_id'] != str(consent['consent_id']) or refs[0]['version'] != consent['version']
            or refs[0]['purpose'] != 'case_guidance'):
        return {'status': 'outdated'}
    documents = conn.execute('SELECT document_id,document_version,source_hash FROM documents WHERE case_id=%s ORDER BY document_id',
                             (case_id,)).fetchall()
    snapshot = [{**d, 'document_id': str(d['document_id'])} for d in documents]
    if (snapshot != sorted(run['document_versions'], key=lambda d: (d['document_id'], d['document_version']))
            or run_input_hash(snapshot, run['pipeline_version'], run.get('context_snapshot')) != run['input_hash']
            or report['input_hash'] != run['input_hash']):
        return {'status': 'outdated'}
    try:
        sources = context_sources(conn, run)
    except ValueError:
        return {'status': 'outdated'}
    evidence = {str(e['evidence_id']): e['text_value'] or '' for e in conn.execute(
        'SELECT evidence_id,text_value FROM evidence WHERE case_id=%s AND run_id=%s',
        (case_id, run['run_id'])).fetchall()}
    sections = build_material_sections(report, evidence, sources,
                                      run['stage_results'].get('reconcile', {}).get('structured_dates'))
    payload = {'sections': sections, 'policy': MATERIAL_POLICY, 'input_hash': run['input_hash']}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    require_conversation(conn, actor_id, conversation_id)
    # A separate stable ID/version: never relabel the pending clinical report as approved.
    return {'status': 'available', 'report_id': str(uuid5(NAMESPACE_URL, f'material:{report["report_id"]}:{digest}')),
            'source_report_version': report['report_version'], 'run_id': str(run['run_id']),
            'policy_version': MATERIAL_POLICY, 'validation_hash': digest, 'sections': sections,
            'document_count': len(documents), 'pending_count': sum(s['pending_count'] for s in sections),
            'notice': '已自动核对材料来源；原文摘录保留疑似、否定等限定，识别结果仍可核实。专业结论和行动建议另行复核。'}
