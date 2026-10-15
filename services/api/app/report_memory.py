"""Frozen, opt-in memory inputs for reports; never clinical evidence."""
from uuid import UUID
from fastapi import HTTPException

from . import memory_repository as store


def lock_snapshot(conn, snapshot):
    memory = (snapshot or {}).get('memory')
    if memory:
        store.lock_scope(conn, UUID(memory['actor_id']), UUID(memory['subject_id']))


def lock_run(conn, case_id, run_id=None):
    row = conn.execute('''SELECT context_snapshot FROM analysis_runs WHERE case_id=%s
        AND (%s::uuid IS NULL OR run_id=%s) ORDER BY created_at DESC LIMIT 1''',
        (case_id, run_id, run_id)).fetchone()
    if row:
        lock_snapshot(conn, row['context_snapshot'])


def capture(conn, actor_id, subject_id, conversation_id):
    """Reuse confirmed statements only after the owner opts this report in."""
    if conversation_id is None or not conn.execute('SELECT 1 FROM user_accounts WHERE actor_id=%s', (actor_id,)).fetchone():
        return None
    from .conversation_repository import require_conversation
    store.lock_scope(conn, actor_id, subject_id)
    current = require_conversation(conn, actor_id, conversation_id, locked=True)
    if not (current['report_memory_enabled'] and current['recall_enabled'] and
            store.settings(conn, actor_id, subject_id)['enabled']):
        return None
    rows = store.active_rows(conn, actor_id, subject_id, current['case_id'], locked=True)
    # Reports have no new user query to rank against. Use bounded explicit preferences
    # and frozen recent confirmations, rather than a document-derived broad query.
    rows = sorted(rows, key=lambda row: (row['kind'] != 'communication_preference', -row['confirmed_at'].timestamp(), str(row['memory_id'])))
    items, used = [], 0
    for row in rows:
        if len(items) == 5:
            break
        if used + len(row['content']) > 2500:
            continue
        used += len(row['content'])
        items.append({'memory_id': str(row['memory_id']), 'version': row['version'], 'kind': row['kind'],
            'field_key': row['field_key'], 'scope': row['scope'], 'content': row['content'],
            'source_turn_id': str(row['source_turn_id']), 'source_case_id': str(row['source_case_id']),
            'source_recorded_at': row['source_recorded_at'].isoformat(), 'confirmed_at': row['confirmed_at'].isoformat(),
            'expires_at': row['expires_at'].isoformat() if row['expires_at'] else None,
            'requires_reconciliation': row['kind']=='confirmed_context' and sum(1 for other in rows
                if (other['kind'],other['field_key'],other['scope'])==(row['kind'],row['field_key'],row['scope'])
                and (row['scope']=='patient' or other['source_case_id']==row['source_case_id']))>1})
    if not items:
        return None
    return {'actor_id': str(actor_id), 'subject_id': str(subject_id), 'conversation_id': str(conversation_id),
            'settings_version': current['memory_settings_version'], 'items': items}


def source_key(item):
    return f"memory:{item['memory_id']}:v{item['version']}"


def references(snapshot):
    return [source_key(item) for item in ((snapshot or {}).get('memory') or {}).get('items', [])]


def sources(conn, case_id, memory, *, lock=False):
    if memory is None:
        return {}
    from .conversation_repository import require_conversation
    actor, subject = memory.actor_id, memory.subject_id
    if lock:
        store.lock_scope(conn, actor, subject)
    try:
        current = require_conversation(conn, actor, memory.conversation_id, locked=lock)
        allowed = store.settings(conn, actor, subject)['enabled']
    except (store.AccessDenied, HTTPException) as exc:
        # Preserve database/operational errors; only an authorization change is stale input.
        if isinstance(exc, store.AccessDenied) or getattr(exc, 'status_code', None) in {403, 404}:
            raise ValueError('REPORT_MEMORY_UNAUTHORIZED') from None
        raise
    if (current['case_id'] != case_id or current['subject_id'] != subject or not allowed
            or not current['recall_enabled'] or not current['report_memory_enabled']
            or current['memory_settings_version'] != memory.settings_version):
        raise ValueError('REPORT_MEMORY_UNAUTHORIZED')
    rows = {(str(row['memory_id']), row['version']): row
            for row in store.active_rows(conn, actor, subject, case_id, locked=lock)}
    result = {}
    for item in memory.items:
        row = rows.get((str(item.memory_id), item.version))
        if row is None or any(str(row[field]) != str(getattr(item, field))
                              for field in ('content', 'source_turn_id', 'source_case_id', 'kind', 'field_key', 'scope')):
            raise ValueError('REPORT_MEMORY_CHANGED')
        if any(row[field] != getattr(item,field) for field in ('source_recorded_at','confirmed_at','expires_at')):
            raise ValueError('REPORT_MEMORY_CHANGED')
        result[source_key(item.model_dump(mode='json'))] = item.content
    return result


def check_report_refs(conn, run, refs, *, lock=False):
    """A valid source list cannot excuse missing/forged report dependency metadata."""
    from .report_context import context_sources
    if refs != references(run.get('context_snapshot')):
        raise ValueError('REPORT_MEMORY_REFERENCES_CHANGED')
    context_sources(conn, run, lock=lock)
