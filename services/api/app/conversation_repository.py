"""Durable chat history. Every read is scoped by owner, subject access and live consent."""

import json
from uuid import UUID, uuid4

from .contracts.core import DataOrigin
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

REPORT_PRESENCE = """EXISTS(SELECT 1 FROM conversation_turns t
    WHERE t.conversation_id=v.conversation_id AND t.input_kind='analysis_ready'
    AND t.status='completed' AND btrim(coalesce(t.answer->>'text',''))<>'') AS has_interpretation_report"""


def require_conversation(conn, actor_id, conversation_id, *, include_report=False):
    projection = "SELECT v.*,c.subject_id" + ("," + REPORT_PRESENCE if include_report else "")
    row = conn.execute(projection + AUTHORIZED + " AND v.conversation_id=%s",
                       (actor_id, conversation_id)).fetchone()
    if not row:
        raise AccessDenied()
    if include_report and not row['has_interpretation_report']:
        row.pop('has_interpretation_report')
    return row


def list_conversations(conn, actor_id, subject_id=None):
    if subject_id is not None:
        access = conn.execute('SELECT 1 FROM actor_subject_access WHERE actor_id=%s AND subject_id=%s AND can_read_case=true',
                              (actor_id,subject_id)).fetchone()
        if not access:
            raise AccessDenied()
    rows = conn.execute("SELECT v.*,c.subject_id," + REPORT_PRESENCE + AUTHORIZED +
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


def create_conversation(conn, actor_id, conversation_id, case_id=None, subject_id=None, recall_enabled=True):
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
            if not get_case(conn, actor_id=actor_id, case_id=case_id):
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
    return conn.execute("""SELECT * FROM (SELECT turn_id,request_id,question,input_kind,attachments,
        CASE WHEN status='running' AND lease_expires_at<=now() THEN 'failed' ELSE status END AS status,
        answer,tool_events,error_code,created_at,finished_at FROM conversation_turns
        WHERE conversation_id=%s AND (%s::uuid IS NULL OR (created_at,turn_id)<
          (SELECT created_at,turn_id FROM conversation_turns WHERE conversation_id=%s AND turn_id=%s))
        ORDER BY created_at DESC,turn_id DESC LIMIT 50) t ORDER BY created_at,turn_id""",
        (conversation_id, before, conversation_id, before)).fetchall()


def begin_turn(conn, actor_id, conversation_id, request_id, question, document_ids, input_kind='user', attachment_ids=()):
    with conn.transaction():
        conversation = require_conversation(conn, actor_id, conversation_id)
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
        require_conversation(conn, actor_id, conversation_id)
        row = conn.execute("""UPDATE conversation_turns SET status=%s,answer=%s::jsonb,
            tool_events=%s::jsonb,error_code=%s,finished_at=now()
            WHERE turn_id=%s AND lease_token=%s AND status='running' RETURNING turn_id""",
            ('failed' if error else 'completed', json.dumps(answer, ensure_ascii=False) if answer else None,
             json.dumps(events or [], ensure_ascii=False), error, turn['turn_id'], turn['lease_token'])).fetchone()
        if not row:
            raise TurnBusy()
        conn.execute('UPDATE conversations SET updated_at=now() WHERE conversation_id=%s', (conversation_id,))
        if not error:
            try:
                from .conversation_titles import enqueue
                with conn.transaction():
                    enqueue(conn, [conversation_id])
            except Exception:
                import logging
                logging.getLogger(__name__).warning('CONVERSATION_TITLE_QUEUE_UNAVAILABLE')


def search_history(conn, actor_id, conversation_id, query):
    current = require_conversation(conn, actor_id, conversation_id)
    if not current['recall_enabled']:
        return {'status': 'disabled', 'messages': []}
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    rows = conn.execute("""SELECT t.turn_id,t.question,t.answer,t.created_at,v.title,v.case_id
        """ + AUTHORIZED.replace(' WHERE v.actor_id=%s',
        " JOIN conversation_turns t ON t.conversation_id=v.conversation_id WHERE v.actor_id=%s") + """
        AND c.subject_id=%s AND v.recall_enabled=true AND t.status='completed'
        AND (t.question ILIKE %s OR t.answer->>'text' ILIKE %s)
        ORDER BY t.created_at DESC LIMIT 12""", (actor_id, current['subject_id'], pattern, pattern)).fetchall()
    return {'status': 'found' if rows else 'empty', 'messages': rows,
            'notice': '历史自述和回答不是新的医学证据，须核对原始材料和最新报告。'}
