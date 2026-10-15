"""Durable chat history. Every read is scoped by owner, subject access and live consent."""

import json
from uuid import UUID, uuid4

from .contracts.core import DataOrigin
from .patient_followup import PatientUpdate, source_patient_updates
from .repository import AccessDenied, IdempotencyConflict, create_case, get_case, get_document


class TurnBusy(Exception):
    pass


AUTHORIZED = """ FROM conversations v JOIN cases c ON c.case_id=v.case_id
    JOIN actors ac ON ac.actor_id=v.actor_id AND ac.active=true
    JOIN actor_subject_access a ON a.subject_id=c.subject_id AND a.actor_id=v.actor_id
      AND a.can_read_case=true
    JOIN consent_purposes p ON p.consent_id=c.consent_id AND p.purpose='case_guidance'
      AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
    WHERE v.actor_id=%s """


def require_conversation(conn, actor_id, conversation_id, *, locked=False):
    row = conn.execute("SELECT v.*,c.subject_id" + AUTHORIZED + " AND v.conversation_id=%s" +
                       (" FOR SHARE OF v,ac,a,p" if locked else ""),
                       (actor_id, conversation_id)).fetchone()
    if not row:
        raise AccessDenied()
    return row


def list_conversations(conn, actor_id, subject_id=None):
    if subject_id is not None:
        access = conn.execute('SELECT 1 FROM actor_subject_access WHERE actor_id=%s AND subject_id=%s AND can_read_case=true',
                              (actor_id,subject_id)).fetchone()
        if not access:
            raise AccessDenied()
    rows = conn.execute("""SELECT v.*,c.subject_id,EXISTS(
                            SELECT 1 FROM conversation_turns t WHERE t.conversation_id=v.conversation_id
                            AND t.input_kind='analysis_ready' AND t.status='completed'
                            AND btrim(coalesce(t.answer->>'text',''))<>'') AS has_interpretation_report""" + AUTHORIZED +
                        " AND (%s::uuid IS NULL OR c.subject_id=%s) ORDER BY v.updated_at DESC,v.conversation_id" +
                        (" LIMIT 100" if subject_id is None else ""),
                        (actor_id,subject_id,subject_id)).fetchall()
    for row in rows:
        if not row['has_interpretation_report']:
            row.pop('has_interpretation_report')
    return rows


def available_subjects(conn, actor_id):
    return conn.execute("""SELECT co.subject_id,co.consent_id FROM consents co
        JOIN actor_subject_access a ON a.subject_id=co.subject_id AND a.actor_id=%s
          AND a.can_create_case=true AND a.can_read_case=true
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>now())
        ORDER BY co.created_at DESC""", (actor_id,)).fetchall()


def create_conversation(conn, actor_id, conversation_id, case_id=None, subject_id=None, recall_enabled=False):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(conversation_id),))
        old = conn.execute("SELECT * FROM conversations WHERE conversation_id=%s", (conversation_id,)).fetchone()
        if old:
            found = require_conversation(conn, actor_id, conversation_id)
            if ((case_id and found['case_id'] != case_id)
                    or (subject_id and found['subject_id'] != subject_id)):
                raise IdempotencyConflict()
            return found
        if case_id:
            selected_case = get_case(conn, actor_id=actor_id, case_id=case_id)
            if not selected_case or (subject_id and selected_case.subject_id != subject_id):
                raise AccessDenied()
        else:
            choices = available_subjects(conn, actor_id)
            if subject_id:
                choices = [x for x in choices if x['subject_id'] == subject_id]
            if not choices or len({x['subject_id'] for x in choices}) != 1:
                raise ValueError("请选择已授权的关怀对象")
            selected = choices[0]
            case, _ = create_case(conn, actor_id=actor_id, subject_id=selected['subject_id'],
                consent_id=selected['consent_id'], source_ref='conversation-upload', external_case_ref=None,
                user_context=None, data_origin=DataOrigin.synthetic, idempotency_key=f'chat:{conversation_id}')
            case_id = case.case_id
        conn.execute("""INSERT INTO conversations(conversation_id,actor_id,case_id,recall_enabled)
            VALUES (%s,%s,%s,%s) RETURNING *""", (conversation_id, actor_id, case_id, recall_enabled)).fetchone()
        return require_conversation(conn, actor_id, conversation_id)


def get_turns(conn, actor_id, conversation_id, before=None):
    require_conversation(conn, actor_id, conversation_id)
    # A cursor lets the UI recover ALL history, without an unbounded response.
    rows = conn.execute("""SELECT * FROM (SELECT turn_id,request_id,question,input_kind,attachments,
        CASE WHEN status='running' AND lease_expires_at<=now() THEN 'failed' ELSE status END AS status,
        answer,tool_events,error_code,created_at,finished_at FROM conversation_turns
        WHERE conversation_id=%s AND (%s::uuid IS NULL OR (created_at,turn_id)<
          (SELECT created_at,turn_id FROM conversation_turns WHERE conversation_id=%s AND turn_id=%s))
        ORDER BY created_at DESC,turn_id DESC LIMIT 50) t ORDER BY created_at,turn_id""",
        (conversation_id, before, conversation_id, before)).fetchall()
    from .memory_repository import references_available, history_references_available
    for row in rows:
        refs = (row.get('answer') or {}).get('memory_refs') or []
        history_refs = (row.get('answer') or {}).get('history_source_refs') or []
        if not references_available(conn, actor_id, conversation_id, refs, strict_epoch=False) or not history_references_available(conn, actor_id, conversation_id, history_refs, strict_epoch=False):
            row['answer'] = {'text': '这条回答引用的历史记忆已变化，请重新提问。',
                             'evidence_refs': [], 'history_refs': [], 'memory_unavailable': True}
    return rows


def begin_turn(conn, actor_id, conversation_id, request_id, question, document_ids, input_kind='user', attachment_ids=()):
    with conn.transaction():
        conversation = require_conversation(conn, actor_id, conversation_id)
        from .memory_repository import lock_scope
        lock_scope(conn, actor_id, conversation['subject_id'])
        conn.execute("SELECT conversation_id FROM conversations WHERE conversation_id=%s FOR UPDATE", (conversation_id,))
        attachments = []
        for document_id in document_ids:
            found = get_document(conn, actor_id=actor_id, case_id=conversation['case_id'], document_id=document_id)
            if not found:
                raise AccessDenied()
            doc, _ = found
            attachments.append({'document_id': str(doc.document_id), 'document_version': doc.document_version,
                                'name': doc.source_ref})
        for attachment_id in dict.fromkeys(attachment_ids):
            from .chat_attachments import get_attachment
            item = get_attachment(conn, actor_id, conversation_id, attachment_id)
            attachments.append({'document_id': str(item['attachment_id']), 'document_version': 1,
                                'name': item['name'], 'kind': 'chat_attachment'})
        old = conn.execute("SELECT * FROM conversation_turns WHERE conversation_id=%s AND request_id=%s",
                           (conversation_id, request_id)).fetchone()
        if old and (old['question'] != question or old['attachments'] != attachments or old['input_kind'] != input_kind):
            raise IdempotencyConflict()
        if old and old['status'] == 'completed':
            from .memory_repository import references_available, history_references_available, MemoryChanged
            if (not references_available(conn, actor_id, conversation_id, (old.get('answer') or {}).get('memory_refs') or [], strict_epoch=False)
                    or not history_references_available(conn, actor_id, conversation_id, (old.get('answer') or {}).get('history_source_refs') or [], strict_epoch=False)):
                raise MemoryChanged()
            return old
        busy = conn.execute("""SELECT 1 FROM conversation_turns WHERE conversation_id=%s
            AND status='running' AND lease_expires_at>now()""", (conversation_id,)).fetchone()
        if busy:
            raise TurnBusy()
        conn.execute("""UPDATE conversation_turns SET status='failed',error_code='TURN_INTERRUPTED'
            WHERE conversation_id=%s AND status='running' AND lease_expires_at<=now()""", (conversation_id,))
        lease = uuid4()
        if old:
            return conn.execute("""UPDATE conversation_turns SET status='running',error_code=NULL,
                lease_token=%s,lease_expires_at=now()+interval '3 minutes'
                WHERE turn_id=%s RETURNING *""", (lease, old['turn_id'])).fetchone()
        row = conn.execute("""INSERT INTO conversation_turns(turn_id,conversation_id,request_id,question,input_kind,
            attachments,status,lease_token,lease_expires_at) VALUES (%s,%s,%s,%s,%s,%s::jsonb,'running',%s,
            now()+interval '3 minutes') RETURNING *""",
            (uuid4(), conversation_id, request_id, question, input_kind, json.dumps(attachments), lease)).fetchone()
        conn.execute("""UPDATE conversations SET updated_at=now(),
            title=CASE WHEN title='新的关怀对话' THEN %s ELSE title END WHERE conversation_id=%s""",
            (question[:30], conversation_id))
        return row


def finish_turn(conn, actor_id, conversation_id, turn, answer=None, events=None, error=None):
    with conn.transaction():
        current = require_conversation(conn, actor_id, conversation_id)
        from .memory_repository import lock_scope
        lock_scope(conn, actor_id, current['subject_id'])
        require_conversation(conn, actor_id, conversation_id, locked=True)
        if answer and answer.get('memory_suggestions'):
            from .memory_service import suggestions_allowed
            if not suggestions_allowed(conn, actor_id, conversation_id):
                answer = {**answer, 'memory_suggestions': []}
        if answer and (answer.get('memory_refs') or answer.get('history_source_refs')):
            from .memory_service import persist_refs
            persist_refs(conn, actor_id, conversation_id, turn['turn_id'], answer.get('memory_refs') or [], answer.get('history_source_refs') or [])
        if answer and answer.get('patient_updates'):
            # Store the self-report atomically with its successful source turn;
            # retries cannot create duplicate profile entries or partial writes.
            answer = {**answer, 'patient_updates': [] if turn['input_kind'] != 'user' else
                      source_patient_updates([PatientUpdate.model_validate(item)
                                              for item in answer['patient_updates']], turn['question'])}
        row = conn.execute("""UPDATE conversation_turns SET status=%s,answer=%s::jsonb,
            tool_events=%s::jsonb,error_code=%s,finished_at=now()
            WHERE turn_id=%s AND lease_token=%s AND status='running' RETURNING turn_id""",
            ('failed' if error else 'completed', json.dumps(answer, ensure_ascii=False) if answer else None,
             json.dumps(events or [], ensure_ascii=False), error, turn['turn_id'], turn['lease_token'])).fetchone()
        if not row:
            raise TurnBusy()
        conn.execute('UPDATE conversations SET updated_at=now() WHERE conversation_id=%s', (conversation_id,))
        if answer and not error:
            from .memory_service import propose_from_answer
            propose_from_answer(conn, actor_id, conversation_id, turn, answer)
        if not error:
            try:
                from .conversation_titles import enqueue
                with conn.transaction():
                    enqueue(conn, [conversation_id])
            except Exception:
                import logging
                logging.getLogger(__name__).warning('CONVERSATION_TITLE_QUEUE_UNAVAILABLE')


def get_patient_context(conn, actor_id, conversation_id):
    """Project current-session statements; cross-session facts use confirmed memory.

    Keeping statements on their original turn also avoids a second store that
    could outlive a revoked consent or a disabled conversation recall setting.
    """
    current = require_conversation(conn, actor_id, conversation_id)
    rows = conn.execute("""SELECT t.turn_id,t.question,t.answer->'patient_updates' AS updates,
        t.created_at,v.case_id """ + AUTHORIZED.replace(' WHERE v.actor_id=%s',
        ' JOIN conversation_turns t ON t.conversation_id=v.conversation_id WHERE v.actor_id=%s') + """
        AND c.subject_id=%s AND t.status='completed' AND t.input_kind='user'
        AND v.conversation_id=%s
        AND jsonb_typeof(t.answer->'patient_updates')='array'
        AND t.answer->'patient_updates'<>'[]'::jsonb
        ORDER BY t.created_at DESC,t.turn_id DESC LIMIT 20""",
        (actor_id, current['subject_id'], conversation_id)).fetchall()
    context, seen, size = [], set(), 0
    for row in rows:
        updates = source_patient_updates([PatientUpdate.model_validate(item) for item in row['updates']], row['question'])
        for item in updates:
            key = (str(row['case_id']), item['field'])
            if key in seen or size + len(item['statement']) > 6000:
                continue
            seen.add(key)
            size += len(item['statement'])
            context.append({**item, 'source_kind': 'patient_statement', 'turn_id': str(row['turn_id']),
                            'case_id': str(row['case_id']), 'recorded_at': row['created_at'].isoformat()})
            if len(context) >= 12:
                return context
    return context



def search_history(conn, actor_id, conversation_id, query):
    current = require_conversation(conn, actor_id, conversation_id)
    from . import automatic_memory
    if automatic_memory.enabled() and conn.execute('SELECT 1 FROM user_accounts WHERE actor_id=%s', (actor_id,)).fetchone():
        return automatic_memory.search(conn, actor_id, conversation_id, query)
    from .memory_repository import settings, lock_scope, memory_consent_version
    lock_scope(conn, actor_id, current['subject_id'])
    state = settings(conn, actor_id, current['subject_id'])
    if not current['recall_enabled'] or not state['enabled']:
        return {'status': 'disabled', 'messages': []}
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    rows = conn.execute("""SELECT t.turn_id,t.question,t.answer,t.created_at,v.title,v.case_id,co.version AS consent_version,v.memory_settings_version AS source_version
        """ + AUTHORIZED.replace(' WHERE v.actor_id=%s',
        " JOIN conversation_turns t ON t.conversation_id=v.conversation_id JOIN consents co ON co.consent_id=c.consent_id WHERE v.actor_id=%s") + """
        AND c.subject_id=%s AND v.memory_export_enabled=true AND t.status='completed'
        AND co.subject_id=c.subject_id
        AND COALESCE(t.answer->'memory_refs','[]'::jsonb)='[]'::jsonb
        AND COALESCE(t.answer->'history_source_refs','[]'::jsonb)='[]'::jsonb
        AND (t.question ILIKE %s OR t.answer->>'text' ILIKE %s)
        ORDER BY t.created_at DESC LIMIT 12""", (actor_id, current['subject_id'], pattern, pattern)).fetchall()
    return {'status': 'found' if rows else 'empty', 'messages': rows, 'policy_epoch': state['epoch'],
            'memory_consent_version': memory_consent_version(conn, actor_id, current['subject_id']),
            'notice': '历史自述和回答不是新的医学证据，须核对原始材料和最新报告。'}
