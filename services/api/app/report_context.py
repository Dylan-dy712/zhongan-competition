"""Frozen user expressions, separate from medical evidence and model answers."""
from typing import Literal
from uuid import UUID

from pydantic import Field
from .contracts.core import Contract
from .report_builder import POLICY_VERSION
from .report_llm import PROMPT_VERSION


class UserTurn(Contract):
    turn_id:UUID
    text:str=Field(min_length=1,max_length=8000)


class ChatContext(Contract):
    conversation_id:UUID
    actor_id:UUID
    sharing_version:int=Field(ge=1)
    anchor_turn_id:UUID
    truncated:bool
    turns:list[UserTurn]=Field(max_length=12)


class ContextSnapshot(Contract):
    version:Literal['care-context-v1']='care-context-v1'
    consent_id:UUID
    consent_version:int=Field(ge=1)
    policy_version:str
    prompt_version:str
    case_user_context:dict | None=None
    chat:ChatContext | None=None


def capture_context(conn,case_id,actor_id,conversation_id=None,turn_id=None):
    scope=conn.execute("""SELECT c.user_context,c.consent_id,co.version FROM cases c
        JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        WHERE c.case_id=%s FOR SHARE OF c,co""",(case_id,)).fetchone()
    if not scope:
        raise ValueError('context case is unavailable')
    chat=None
    if conversation_id is not None:
        current=conn.execute("""SELECT * FROM conversations WHERE conversation_id=%s AND actor_id=%s
            AND case_id=%s FOR SHARE""",(conversation_id,actor_id,case_id)).fetchone()
        if not current:
            raise ValueError('context conversation is outside actor/case scope')
        if current['report_context_enabled']:
            anchor=conn.execute('SELECT * FROM conversation_turns WHERE conversation_id=%s AND turn_id=%s FOR SHARE',
                                (conversation_id,turn_id)).fetchone()
            if not anchor or anchor['status'] not in {'completed','running'}:
                raise ValueError('analysis requires a persisted initiating turn')
            rows=conn.execute("""SELECT turn_id,question FROM conversation_turns WHERE conversation_id=%s
                AND input_kind='user' AND (status='completed' OR turn_id=%s)
                AND (created_at,turn_id)<=(%s,%s) ORDER BY created_at DESC,turn_id DESC LIMIT 13 FOR SHARE""",
                (conversation_id,turn_id,anchor['created_at'],turn_id)).fetchall()
            chat=ChatContext(conversation_id=conversation_id,actor_id=actor_id,
                sharing_version=current['report_context_version'],anchor_turn_id=turn_id,truncated=len(rows)>12,
                turns=[UserTurn(turn_id=row['turn_id'],text=row['question']) for row in reversed(rows[:12])])
    return ContextSnapshot(consent_id=scope['consent_id'],consent_version=scope['version'],
        policy_version=POLICY_VERSION,prompt_version=PROMPT_VERSION,case_user_context=scope['user_context'],
        chat=chat).model_dump(mode='json')


def context_sources(conn,run,*,lock=False):
    """Recheck consent and sharing at generation, review, release and patient reads."""
    raw=run.get('context_snapshot')
    if raw is None:
        row=conn.execute('SELECT user_context FROM cases WHERE case_id=%s',(run['case_id'],)).fetchone()
        return {'case:user_context':str(row['user_context'])} if row and row['user_context'] else {}
    snap=ContextSnapshot.model_validate(raw)
    if snap.policy_version!=POLICY_VERSION:
        raise ValueError('report context policy changed; regenerate')
    scope=conn.execute("""SELECT 1 FROM cases c JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE c.case_id=%s AND co.consent_id=%s AND co.version=%s"""+
        (' FOR SHARE OF c,co,p' if lock else ''),(run['case_id'],snap.consent_id,snap.consent_version)).fetchone()
    if not scope:
        raise ValueError('REPORT_CONTEXT_UNAUTHORIZED')
    sources={'case:user_context':str(snap.case_user_context)} if snap.case_user_context else {}
    if snap.chat:
        chat=snap.chat
        allowed=conn.execute("""SELECT 1 FROM conversations v JOIN cases c ON c.case_id=v.case_id
            JOIN actors ac ON ac.actor_id=v.actor_id AND ac.active=true
            JOIN actor_subject_access a ON a.actor_id=ac.actor_id AND a.subject_id=c.subject_id AND a.can_read_case=true
            WHERE v.conversation_id=%s AND v.actor_id=%s AND v.case_id=%s
              AND v.report_context_enabled=true AND v.report_context_version=%s"""+
            (' FOR SHARE OF v,ac,a' if lock else ''),
            (chat.conversation_id,chat.actor_id,run['case_id'],chat.sharing_version)).fetchone()
        if not allowed:
            raise ValueError('REPORT_CONTEXT_UNAUTHORIZED')
        for turn in chat.turns:
            source=conn.execute("""SELECT question FROM conversation_turns WHERE conversation_id=%s AND turn_id=%s
                AND input_kind='user'"""+(' FOR SHARE' if lock else ''),(chat.conversation_id,turn.turn_id)).fetchone()
            if not source or source['question']!=turn.text:
                raise ValueError('frozen user expression does not match its source')
            sources[f'conversation:{chat.conversation_id}:turn:{turn.turn_id}:user']=turn.text
    return sources


def report_sources(conn,case_id,run_id,*,lock=False):
    run=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE case_id=%s AND run_id=%s',
                     (case_id,run_id)).fetchone()
    if not run:
        raise ValueError('report source run is unavailable')
    return context_sources(conn,run,lock=lock)
