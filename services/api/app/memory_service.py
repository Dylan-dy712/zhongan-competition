"""Bounded Semantix retrieval over a corpus already authorized by PostgreSQL."""
import json
import math
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from . import memory_repository as memories

PROTOCOL = 'zhongan-memory-rank-v1'
UPSTREAM = '5e546dcb69b7545e9fba9f95f9464c0ddd6f9cff'


def rank_documents(query, rows):
    executable = os.getenv('ZHONGAN_MEMORY_RANKER') or str(Path(__file__).resolve().parents[3] /
        'output_dir/memory-ranker' / ('semantix-ranker.exe' if os.name == 'nt' else 'semantix-ranker'))
    request_id = str(uuid4())
    documents = {f"{row['memory_id']}:{row['version']}": row for row in rows}
    if len(documents) > 256:
        raise ValueError('MEMORY_CORPUS_LIMIT')
    payload = {'protocol': PROTOCOL, 'request_id': request_id, 'query': query,
               'documents': [{'id': key, 'content': row['content']} for key, row in documents.items()]}
    result = subprocess.run([executable], input=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                            capture_output=True, timeout=2, check=True, shell=False)
    if len(result.stdout) > 100000:
        raise ValueError('MEMORY_PROTOCOL_INVALID')
    response = json.loads(result.stdout)
    if (response.get('protocol') != PROTOCOL or response.get('request_id') != request_id
            or response.get('upstream') != UPSTREAM or response.get('retriever') != 'semantix-bm25'
            or not isinstance(response.get('hits'), list) or len(response['hits']) > 256):
        raise ValueError('MEMORY_PROTOCOL_INVALID')
    selected, seen = [], set()
    top = 0.0
    for hit in response['hits']:
        key, score, coverage = hit.get('id'), hit.get('score'), hit.get('coverage')
        if (key not in documents or key in seen or type(score) not in (int, float) or not math.isfinite(score)
                or score <= 0 or type(coverage) not in (int, float) or not 0 <= coverage <= 1):
            raise ValueError('MEMORY_PROTOCOL_INVALID')
        seen.add(key)
        top = max(top, score)
        # Conservative lexical gates, to be calibrated on the project's Chinese corpus.
        if coverage >= .25 and score >= top * .55:
            selected.append(documents[key])
    return selected[:5]


def prepare_context(conn, actor, conversation_id, question, history):
    snapshot, safe_history = _prepare_confirmed_context(conn, actor, conversation_id, question, history)
    snapshot['allow_suggestions'] = False
    from .automatic_memory import extend_context
    return extend_context(conn, actor, conversation_id, question, snapshot, safe_history)


def _prepare_confirmed_context(conn, actor, conversation_id, question, history):
    from .conversation_repository import require_conversation
    current = require_conversation(conn, actor, conversation_id)
    empty = {'items': [], 'refs': [], 'history_refs': [], 'status': 'disabled', 'allow_suggestions': False}
    is_account = conn.execute('SELECT 1 FROM user_accounts WHERE actor_id=%s', (actor,)).fetchone()
    if not is_account:
        return empty, [row for row in history if not (row.get('answer') or {}).get('memory_refs')
                       and not (row.get('answer') or {}).get('history_source_refs')
                       and not (row.get('answer') or {}).get('memory_unavailable')]
    memories.lock_scope(conn, actor, current['subject_id'])
    state = memories.settings(conn, actor, current['subject_id'])
    empty['allow_suggestions'] = state['enabled'] and current['memory_export_enabled']
    readable = state['enabled'] and current['recall_enabled']
    rows = memories.active_rows(conn, actor, current['subject_id'], current['case_id']) if readable else []
    allowed = {(str(row['memory_id']), row['version']) for row in rows}
    safe_history, inherited, inherited_history = [], {}, {}
    for turn in history:
        answer = turn.get('answer') or {}
        refs = answer.get('memory_refs') or []
        history_refs = answer.get('history_source_refs') or []
        if answer.get('memory_unavailable'):
            continue
        if refs and (not readable or any((str(ref.get('memory_id')), ref.get('version')) not in allowed for ref in refs)):
            continue
        if history_refs and not memories.history_references_available(conn, actor, conversation_id, history_refs, strict_epoch=False):
            continue
        safe_history.append(turn)
    from .conversation_agent import bounded_history
    safe_history = bounded_history(safe_history)
    for turn in safe_history:
        refs = (turn.get('answer') or {}).get('memory_refs') or []
        history_refs = (turn.get('answer') or {}).get('history_source_refs') or []
        for ref in refs:
            inherited[(str(ref['memory_id']), ref['version'])] = {**ref, 'epoch': state['epoch']}
        for ref in history_refs:
            inherited_history[str(ref['source_turn_id'])] = {**ref, 'epoch': state['epoch']}
    conn.commit()  # No transaction or authorization lock spans a subprocess/model call.
    if not readable:
        return empty, safe_history
    status = 'empty'
    selected = []
    if rows:
        try:
            ranked = rank_documents(question, rows)
            # Explicit communication preferences are always relevant, unlike clinical context.
            preferences = [row for row in rows if row['kind'] == 'communication_preference']
            selected = list({(str(row['memory_id']), row['version']): row for row in [*preferences, *ranked]}.values())[:5]
            status = 'available' if selected else 'empty'
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            status = 'retrieval_unavailable'
    items, size = [], 0
    refs = dict(inherited)
    for row in selected:
        if size + len(row['content']) > 2500:
            continue
        size += len(row['content'])
        key = (str(row['memory_id']), row['version'])
        refs[key] = {'memory_id': key[0], 'version': key[1], 'epoch': state['epoch']}
        items.append({'memory_id': key[0], 'version': key[1], 'kind': row['kind'], 'field_key': row['field_key'],
                      'content': row['content'], 'scope': row['scope'], 'source_case_id': str(row['source_case_id']),
                      'source_turn_id': str(row['source_turn_id']), 'confirmed_at': row['confirmed_at'].isoformat(),
                      'source_recorded_at': row['source_recorded_at'].isoformat(),
                      'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
                      'source_kind': 'user_confirmed_statement', 'medical_verification': False})
        if row['kind'] == 'confirmed_context':
            items[-1]['requires_reconciliation'] = sum(1 for candidate in rows
                if candidate['kind'] == 'confirmed_context' and candidate['field_key'] == row['field_key']
                and candidate['scope'] == row['scope'] and (row['scope'] == 'patient' or
                    candidate['source_case_id'] == row['source_case_id'])) > 1
    snapshot = {'items': items, 'refs': list(refs.values()), 'history_refs': list(inherited_history.values()),
                'status': status, 'allow_suggestions': empty['allow_suggestions']}
    validate_context(conn, actor, conversation_id, snapshot)
    conn.commit()
    return snapshot, safe_history


def validate_context(conn, actor, conversation_id, snapshot):
    if snapshot and (not memories.references_available(conn, actor, conversation_id, snapshot.get('refs') or [], locked=True)
            or not memories.history_references_available(conn, actor, conversation_id, snapshot.get('history_refs') or [], locked=True)):
        raise memories.MemoryChanged()


def persist_refs(conn, actor, conversation_id, turn_id, refs, history_refs=()):
    if (not memories.references_available(conn, actor, conversation_id, refs, locked=True)
            or not memories.history_references_available(conn, actor, conversation_id, history_refs, locked=True)):
        raise memories.MemoryChanged()
    for ref in refs:
        conn.execute('''INSERT INTO chat_memory_refs(turn_id,memory_id,memory_version,policy_epoch)
            VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (turn_id, ref['memory_id'], ref['version'], ref['epoch']))
    for ref in history_refs:
        conn.execute('''INSERT INTO chat_history_refs(turn_id,source_turn_id,source_consent_version,source_settings_version,memory_consent_version,policy_epoch)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
            (turn_id, ref['source_turn_id'], ref['consent_version'], ref['source_version'], ref['memory_consent_version'], ref['epoch']))


def suggestions_allowed(conn, actor, conversation_id):
    return False  # Manual candidate collection has been retired.


def propose_from_answer(conn, actor, conversation_id, turn, answer):
    """Compatibility hook: source turns themselves are the automatic memory."""
    return
