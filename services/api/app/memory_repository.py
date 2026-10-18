"""Authoritative, account/patient-scoped memory. Ranking never grants access."""
import json
from uuid import uuid4

from fastapi import HTTPException

from . import accounts
from .repository import AccessDenied, IdempotencyConflict, request_digest

PURPOSE = 'continuous_care_memory'


class MemoryChanged(ValueError):
    def __init__(self):
        super().__init__('MEMORY_CONTEXT_CHANGED')


def require_member(conn, actor, subject):
    accounts.member_scope(conn, actor, subject)
    if not conn.execute('''SELECT 1 FROM actor_subject_access a JOIN actors ac USING(actor_id)
        WHERE a.actor_id=%s AND a.subject_id=%s AND a.can_read_case=true AND ac.active=true''',
        (actor, subject)).fetchone():
        raise AccessDenied()


def lock_scope(conn, actor, subject):
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'care-memory:{actor}:{subject}',))


def settings(conn, actor, subject):
    require_member(conn, actor, subject)
    row = conn.execute('''SELECT s.*, (s.enabled AND p.status='active'
        AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())) AS effective
        FROM patient_memory_settings s LEFT JOIN consents c ON c.consent_id=s.consent_id AND c.subject_id=s.subject_id
        LEFT JOIN consent_purposes p ON p.consent_id=c.consent_id AND p.purpose=%s
        WHERE s.actor_id=%s AND s.subject_id=%s''', (PURPOSE, actor, subject)).fetchone()
    return {'subject_id': subject, 'enabled': bool(row and row['effective']),
            'version': row['version'] if row else 0, 'epoch': row['epoch'] if row else 0,
            'purpose': PURPOSE}


def _operation(conn, actor, subject, key, payload):
    previous = conn.execute('''SELECT request_hash,response FROM care_memory_operations
        WHERE actor_id=%s AND subject_id=%s AND idempotency_key=%s''', (actor, subject, key)).fetchone()
    if previous and previous['request_hash'] != request_digest(payload):
        raise IdempotencyConflict()
    return previous['response'] if previous else None


def _record(conn, actor, subject, key, payload, response):
    conn.execute('INSERT INTO care_memory_operations(actor_id,subject_id,idempotency_key,request_hash,response) VALUES (%s,%s,%s,%s,%s::jsonb)',
                 (actor, subject, key, request_digest(payload), json.dumps(response, default=str)))
    return response


def change_settings(conn, actor, subject, body, key):
    with conn.transaction():
        require_member(conn, actor, subject)
        lock_scope(conn, actor, subject)
        payload = {'operation': 'settings', **body.model_dump(mode='json')}
        conn.execute('INSERT INTO patient_memory_settings(actor_id,subject_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', (actor, subject))
        previous = _operation(conn, actor, subject, key, payload)
        if previous is not None:
            return settings(conn, actor, subject)  # Never replay a superseded grant.
        current = settings(conn, actor, subject)
        if current['version'] != body.expected_version:
            raise HTTPException(409, '记忆设置已更新，请刷新后重试。')
        row = conn.execute('SELECT * FROM patient_memory_settings WHERE actor_id=%s AND subject_id=%s', (actor, subject)).fetchone()
        if current['enabled'] == body.enabled and row['enabled'] == body.enabled:
            return _record(conn, actor, subject, key, payload, current)
        consent = row['consent_id']
        if body.enabled and accounts.care_consent(conn, actor, subject)['status'] != 'active':
            raise HTTPException(409, '请先确认该就诊人的本次关怀用途。')
        if consent is None:
            consent = uuid4()
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'care-memory-v1',1)", (consent, subject))
            conn.execute('''INSERT INTO consent_purposes(consent_id,purpose,status,granted_at,revoked_at)
                VALUES (%s,%s,%s,now(),CASE WHEN %s THEN NULL ELSE now() END)''',
                (consent, PURPOSE, 'active' if body.enabled else 'revoked', body.enabled))
        else:
            conn.execute('UPDATE consents SET version=version+1 WHERE consent_id=%s', (consent,))
            conn.execute('''UPDATE consent_purposes SET status=%s,granted_at=now(),expires_at=NULL,
                revoked_at=CASE WHEN %s THEN NULL ELSE now() END WHERE consent_id=%s AND purpose=%s''',
                ('active' if body.enabled else 'revoked', body.enabled, consent, PURPOSE))
        # A new grant never revives content captured under a previous grant.
        conn.execute("UPDATE care_memories SET status='revoked' WHERE actor_id=%s AND subject_id=%s AND status='active'", (actor, subject))
        conn.execute("UPDATE care_memory_candidates SET status='dismissed',version=version+1 WHERE actor_id=%s AND subject_id=%s AND status='pending'", (actor, subject))
        conn.execute('''UPDATE patient_memory_settings SET enabled=%s,version=version+1,epoch=epoch+1,consent_id=%s
            WHERE actor_id=%s AND subject_id=%s''', (body.enabled, consent, actor, subject))
        result = settings(conn, actor, subject)
        return _record(conn, actor, subject, key, payload, result)


def require_source(conn, actor, subject, turn_id, *, locked=False):
    row = conn.execute('''SELECT t.*,v.case_id,c.consent_id,co.version AS consent_version
        FROM conversation_turns t JOIN conversations v USING(conversation_id)
        JOIN cases c ON c.case_id=v.case_id JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
        JOIN actors ac ON ac.actor_id=v.actor_id
        JOIN actor_subject_access a ON a.actor_id=v.actor_id AND a.subject_id=c.subject_id
        WHERE t.turn_id=%s AND v.actor_id=%s AND c.subject_id=%s
          AND t.input_kind='user' AND t.status='completed' AND v.memory_export_enabled=true
          AND ac.active=true AND a.can_read_case=true AND p.status='active'
          AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())''' +
        (' FOR SHARE OF v,co,p,ac,a' if locked else ''), (turn_id, actor, subject)).fetchone()
    if not row:
        raise AccessDenied()
    return row


def memory_consent_version(conn, actor, subject):
    row = conn.execute('''SELECT c.version FROM patient_memory_settings s JOIN consents c ON c.consent_id=s.consent_id
        WHERE s.actor_id=%s AND s.subject_id=%s''', (actor, subject)).fetchone()
    return row['version'] if row else 0


def create_candidate(conn, actor, subject, body):
    with conn.transaction():
        require_member(conn, actor, subject)
        lock_scope(conn, actor, subject)
        if not settings(conn, actor, subject)['enabled']:
            raise HTTPException(409, '请先为该就诊人开启长期关怀记忆。')
        source = require_source(conn, actor, subject, body.source_turn_id, locked=True)
        if body.content not in source['question']:
            raise HTTPException(422, '记忆内容必须是该条用户消息中的原文，不能保存助手生成的内容。')
        grant_version = memory_consent_version(conn, actor, subject)
        dedup_key = request_digest({'payload': body.model_dump(mode='json'),
            'source_consent_version': source['consent_version'], 'memory_consent_version': grant_version})
        previous = conn.execute('''SELECT * FROM care_memory_candidates WHERE actor_id=%s AND subject_id=%s
            AND dedup_key=%s ORDER BY created_at DESC,candidate_id DESC LIMIT 1''', (actor, subject, dedup_key)).fetchone()
        if previous:
            if previous['status'] == 'pending':
                return previous
            if previous['status'] == 'confirmed' and conn.execute('''SELECT 1 FROM care_memories
                    WHERE candidate_id=%s AND status='active' AND (expires_at IS NULL OR expires_at>clock_timestamp())''',
                    (previous['candidate_id'],)).fetchone():
                return previous
        candidate_id = uuid4()
        conn.execute('''INSERT INTO care_memory_candidates(candidate_id,dedup_key,actor_id,subject_id,source_turn_id,scope,
            case_id,kind,field_key,content,expires_at,source_consent_version,memory_consent_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (candidate_id, dedup_key, actor, subject, body.source_turn_id, body.scope, source['case_id'], body.kind,
             body.field_key, body.content, body.expires_at, source['consent_version'], grant_version))
        return conn.execute('SELECT * FROM care_memory_candidates WHERE candidate_id=%s', (candidate_id,)).fetchone()


def confirm_candidate(conn, actor, subject, candidate_id, body, key):
    with conn.transaction():
        require_member(conn, actor, subject)
        lock_scope(conn, actor, subject)
        if not settings(conn, actor, subject)['enabled']:
            raise HTTPException(409, '长期关怀记忆已关闭。')
        payload = {'operation': 'confirm', 'candidate_id': str(candidate_id), **body.model_dump(mode='json')}
        previous = _operation(conn, actor, subject, key, payload)
        if previous is not None:
            return previous  # Contains identifiers only, never archived patient text.
        candidate = conn.execute('''SELECT *,expires_at IS NOT NULL AND expires_at<=clock_timestamp() AS expired
            FROM care_memory_candidates WHERE candidate_id=%s AND actor_id=%s AND subject_id=%s''',
            (candidate_id, actor, subject)).fetchone()
        if not candidate:
            raise AccessDenied()
        source = require_source(conn, actor, subject, candidate['source_turn_id'], locked=True)
        if (candidate['version'] != body.expected_version or candidate['status'] != 'pending' or candidate['expired']
                or source['consent_version'] != candidate['source_consent_version']
                or memory_consent_version(conn, actor, subject) != candidate['memory_consent_version']):
            raise HTTPException(409, '候选或来源已变化，请重新选择来源并确认。')
        memory_id, version = uuid4(), 1
        if body.replaces_memory_id:
            old = conn.execute('''SELECT * FROM care_memories WHERE memory_id=%s AND version=%s
                AND actor_id=%s AND subject_id=%s AND status='active' ''',
                (body.replaces_memory_id, body.replaces_version, actor, subject)).fetchone()
            if not old:
                raise HTTPException(409, '要更正的记忆版本已变化。')
            if (old['kind'], old['field_key'], old['scope']) != (candidate['kind'], candidate['field_key'], candidate['scope']) or (
                    old['scope'] == 'case' and old['source_case_id'] != candidate['case_id']):
                raise HTTPException(409, '更正必须属于同一记忆类型和适用范围。')
            conn.execute("UPDATE care_memories SET status='superseded' WHERE memory_id=%s AND version=%s", (old['memory_id'], old['version']))
            memory_id, version = old['memory_id'], old['version'] + 1
        elif candidate['kind'] == 'communication_preference' and any(
                (row['kind'], row['field_key'], row['scope']) == (candidate['kind'], candidate['field_key'], candidate['scope'])
                and (row['scope'] == 'patient' or row['source_case_id'] == candidate['case_id'])
                for row in active_rows(conn, actor, subject)):
            raise HTTPException(409, '该偏好已有记忆，请选择更正已有版本。')
        if len(active_rows(conn, actor, subject)) >= 256:
            raise HTTPException(409, '当前有效记忆已达到 256 条，请先停止使用不再需要的记忆。')
        conn.execute('''INSERT INTO care_memories(memory_id,version,actor_id,subject_id,candidate_id,source_turn_id,
            source_case_id,scope,kind,field_key,content,expires_at,source_consent_version,memory_consent_version)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (memory_id, version, actor, subject, candidate_id, candidate['source_turn_id'], candidate['case_id'],
             candidate['scope'], candidate['kind'], candidate['field_key'], candidate['content'], candidate['expires_at'],
             candidate['source_consent_version'], candidate['memory_consent_version']))
        conn.execute("UPDATE care_memory_candidates SET status='confirmed',version=version+1 WHERE candidate_id=%s", (candidate_id,))
        conn.execute('UPDATE patient_memory_settings SET epoch=epoch+1 WHERE actor_id=%s AND subject_id=%s', (actor, subject))
        return _record(conn, actor, subject, key, payload, {'memory_id': str(memory_id), 'version': version, 'status': 'active'})


def revoke_memory(conn, actor, subject, memory_id, expected_version):
    with conn.transaction():
        require_member(conn, actor, subject)
        lock_scope(conn, actor, subject)
        row = conn.execute('''SELECT * FROM care_memories WHERE memory_id=%s AND actor_id=%s AND subject_id=%s
            ORDER BY version DESC LIMIT 1''', (memory_id, actor, subject)).fetchone()
        if not row:
            raise AccessDenied()
        if row['version'] != expected_version:
            raise HTTPException(409, '记忆版本已更新，请刷新后重试。')
        if row['status'] == 'revoked':
            return {'memory_id': str(memory_id), 'version': expected_version, 'status': 'revoked',
                    'cleanup_status': 'stopped_using', 'physical_deletion': False}
        conn.execute("UPDATE care_memories SET status='revoked' WHERE memory_id=%s AND actor_id=%s AND subject_id=%s AND status='active'", (memory_id, actor, subject))
        conn.execute('UPDATE patient_memory_settings SET epoch=epoch+1 WHERE actor_id=%s AND subject_id=%s', (actor, subject))
        return {'memory_id': str(memory_id), 'version': expected_version, 'status': 'revoked',
                'cleanup_status': 'stopped_using', 'physical_deletion': False}


def active_rows(conn, actor, subject, case_id=None, *, locked=False):
    # PRE-filter all authorization and provenance before handing any text to a ranker.
    return conn.execute('''SELECT m.*,t.created_at AS source_recorded_at FROM care_memories m
        JOIN patient_memory_settings s ON s.actor_id=m.actor_id AND s.subject_id=m.subject_id
        JOIN consents mc ON mc.consent_id=s.consent_id AND mc.subject_id=m.subject_id AND mc.version=m.memory_consent_version
        JOIN consent_purposes mp ON mp.consent_id=mc.consent_id AND mp.purpose='continuous_care_memory'
        JOIN conversation_turns t ON t.turn_id=m.source_turn_id
        JOIN conversations v ON v.conversation_id=t.conversation_id AND v.actor_id=m.actor_id AND v.case_id=m.source_case_id
        JOIN cases c ON c.case_id=v.case_id AND c.subject_id=m.subject_id
        JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id AND co.version=m.source_consent_version
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
        JOIN actors ac ON ac.actor_id=m.actor_id
        JOIN actor_subject_access a ON a.actor_id=m.actor_id AND a.subject_id=m.subject_id
        WHERE m.actor_id=%s AND m.subject_id=%s AND m.status='active' AND s.enabled=true
        AND (m.scope='patient' OR m.source_case_id=%s OR %s::uuid IS NULL)
        AND (m.expires_at IS NULL OR m.expires_at>clock_timestamp())
        AND t.status='completed' AND t.input_kind='user' AND v.memory_export_enabled=true
        AND ac.active=true AND a.can_read_case=true AND p.status='active' AND mp.status='active'
        AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        AND (mp.expires_at IS NULL OR mp.expires_at>clock_timestamp())
        ORDER BY m.memory_id,m.version''' + (' FOR SHARE OF s,mc,mp,v,co,p,ac,a' if locked else ''),
        (actor, subject, case_id, case_id)).fetchall()


def references_available(conn, actor, conversation_id, refs, *, locked=False, strict_epoch=True):
    if not refs:
        return True
    from .conversation_repository import require_conversation
    current = require_conversation(conn, actor, conversation_id)
    lock_scope(conn, actor, current['subject_id'])
    if locked:
        # Serializes conversation read/export changes against final delivery.
        current = require_conversation(conn, actor, conversation_id, locked=True)
    state = settings(conn, actor, current['subject_id'])
    if not current['recall_enabled'] or not state['enabled'] or (strict_epoch and any(ref.get('epoch') != state['epoch'] for ref in refs)):
        return False
    allowed = {(str(row['memory_id']), row['version']) for row in active_rows(conn, actor, current['subject_id'], current['case_id'], locked=locked)}
    return all((str(ref.get('memory_id')), ref.get('version')) in allowed for ref in refs)


def list_memories(conn, actor, subject):
    require_member(conn, actor, subject)
    allowed = {(str(row['memory_id']), row['version']) for row in active_rows(conn, actor, subject)}
    rows = conn.execute('''SELECT DISTINCT ON (memory_id) *,
        (expires_at IS NOT NULL AND expires_at<=clock_timestamp()) AS expired FROM care_memories
        WHERE actor_id=%s AND subject_id=%s ORDER BY memory_id,version DESC''', (actor, subject)).fetchall()
    for row in rows:
        if (str(row['memory_id']), row['version']) not in allowed:
            row['content'] = ''
            if row['status'] == 'active':
                row['status'] = 'expired' if row['expired'] else 'unavailable'
    candidates = []
    if settings(conn, actor, subject)['enabled']:
        for row in conn.execute("SELECT * FROM care_memory_candidates WHERE actor_id=%s AND subject_id=%s AND status='pending' ORDER BY created_at DESC LIMIT 100", (actor, subject)).fetchall():
            try:
                source = require_source(conn, actor, subject, row['source_turn_id'])
            except AccessDenied:
                continue
            if source['consent_version'] == row['source_consent_version'] and row['memory_consent_version'] == memory_consent_version(conn, actor, subject):
                candidates.append(row)
    return {'memories': rows, 'candidates': candidates}


def history_references_available(conn, actor, conversation_id, refs, *, locked=False, strict_epoch=True):
    if not refs:
        return True
    from . import automatic_memory
    automatic = [ref for ref in refs if ref.get('memory_consent_version') == 0]
    if automatic and not automatic_memory.available(conn, actor, conversation_id, automatic, locked=locked):
        return False
    refs = [ref for ref in refs if ref.get('memory_consent_version') != 0]
    if not refs:
        return True
    from .conversation_repository import require_conversation
    current = require_conversation(conn, actor, conversation_id)
    lock_scope(conn, actor, current['subject_id'])
    if locked:
        current = require_conversation(conn, actor, conversation_id, locked=True)
    state = settings(conn, actor, current['subject_id'])
    if (not current['recall_enabled'] or not state['enabled']
            or (strict_epoch and any(ref.get('epoch') != state['epoch'] for ref in refs))
            or any(ref.get('memory_consent_version') != memory_consent_version(conn, actor, current['subject_id']) for ref in refs)):
        return False
    rows = conn.execute('''SELECT t.turn_id,co.version AS consent_version,v.memory_settings_version AS source_version
        FROM conversation_turns t JOIN conversations v USING(conversation_id)
        JOIN cases c ON c.case_id=v.case_id JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
        JOIN actors ac ON ac.actor_id=v.actor_id
        JOIN actor_subject_access a ON a.actor_id=v.actor_id AND a.subject_id=c.subject_id
        WHERE t.turn_id=ANY(%s::uuid[]) AND v.actor_id=%s AND c.subject_id=%s
        AND t.status='completed' AND v.memory_export_enabled=true AND ac.active=true AND a.can_read_case=true
        AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())''' +
        (' FOR SHARE OF v,co,p,ac,a' if locked else ''),
        ([ref['source_turn_id'] for ref in refs], actor, current['subject_id'])).fetchall()
    allowed = {(str(row['turn_id']), row['consent_version'], row['source_version']) for row in rows}
    return all((str(ref.get('source_turn_id')), ref.get('consent_version'), ref.get('source_version')) in allowed for ref in refs)


def conversation_settings(conn, actor, conversation_id):
    from .conversation_repository import require_conversation
    row = require_conversation(conn, actor, conversation_id)
    return {'read_enabled': row['recall_enabled'], 'export_enabled': row['memory_export_enabled'],
            'report_enabled': row['report_memory_enabled'],
            'version': row['memory_settings_version']}


def change_conversation_settings(conn, actor, conversation_id, body):
    from .conversation_repository import require_conversation
    with conn.transaction():
        current = require_conversation(conn, actor, conversation_id)
        lock_scope(conn, actor, current['subject_id'])
        current = conn.execute('SELECT * FROM conversations WHERE conversation_id=%s FOR UPDATE', (conversation_id,)).fetchone()
        if current['memory_settings_version'] != body.expected_version:
            raise HTTPException(409, '对话记忆设置已变化，请刷新后重试。')
        enabling = ((body.read_enabled and not current['recall_enabled']) or
                    (body.export_enabled and not current['memory_export_enabled']) or
                    (body.report_enabled and not current['report_memory_enabled']))
        if enabling and not settings(conn, actor, require_conversation(conn, actor, conversation_id)['subject_id'])['enabled']:
            raise HTTPException(409, '请先为当前就诊人开启长期关怀记忆。')
        conn.execute('''UPDATE conversations SET recall_enabled=%s,memory_export_enabled=%s,report_memory_enabled=%s,
            memory_settings_version=memory_settings_version+1 WHERE conversation_id=%s''',
            (body.read_enabled, body.export_enabled, body.report_enabled, conversation_id))
        if current['memory_export_enabled'] and not body.export_enabled:
            conn.execute("""UPDATE care_memories SET status='revoked' WHERE actor_id=%s AND subject_id=%s
                AND status='active' AND source_turn_id IN
                (SELECT turn_id FROM conversation_turns WHERE conversation_id=%s)""",
                (actor, require_conversation(conn, actor, conversation_id)['subject_id'], conversation_id))
            conn.execute("""UPDATE care_memory_candidates SET status='dismissed',version=version+1
                WHERE actor_id=%s AND status='pending' AND source_turn_id IN
                (SELECT turn_id FROM conversation_turns WHERE conversation_id=%s)""", (actor, conversation_id))
        subject = require_conversation(conn, actor, conversation_id)['subject_id']
        conn.execute('UPDATE patient_memory_settings SET epoch=epoch+1 WHERE actor_id=%s AND subject_id=%s', (actor, subject))
        return conversation_settings(conn, actor, conversation_id)
