"""Patient memory HTTP boundary; identities always come from authentication."""
from uuid import UUID
from fastapi import Depends, Header, HTTPException

from . import memory_repository as store
from .contracts.memory import (MemoryCandidateCreate, MemoryCandidateResponse, MemoryConfirm,
    MemoryConsentChange, MemorySettingsResponse, MemoryListResponse, MemoryItemResponse, MemoryRevoke, ConversationMemoryChange, ConversationMemoryResponse,
    ReportMemorySourcesResponse)


def register_memory_routes(app, current_actor, database):
    def require_manual_mode():
        from .automatic_memory import enabled
        if enabled():
            raise HTTPException(410, '已改为自动承接历史对话，无需提交或确认记忆。')

    def public(model, row):
        return model.model_validate({key: row[key] for key in model.model_fields if key in row})

    @app.exception_handler(store.MemoryChanged)
    async def memory_changed(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={'code': 'MEMORY_CONTEXT_CHANGED',
            'message': '使用的历史记忆或授权已变化，请重新提问。', 'retryable': True})

    @app.get('/v1/me/members/{subject_id}/memory-settings', response_model=MemorySettingsResponse)
    def get_settings(subject_id: UUID, actor=Depends(current_actor), conn=Depends(database)):
        return store.settings(conn, actor, subject_id)

    @app.get('/v1/cases/{case_id}/reports/{version}/memory-sources',response_model=ReportMemorySourcesResponse)
    def report_memory_sources(case_id:UUID,version:int,actor=Depends(current_actor),conn=Depends(database)):
        from .repository import get_report
        from .report_memory import lock_run,check_report_refs,source_key
        with conn.transaction():
            row=conn.execute('SELECT run_id FROM reports WHERE case_id=%s AND report_version=%s',(case_id,version)).fetchone()
            if not row:
                raise HTTPException(404,'报告当前不可访问。')
            lock_run(conn,case_id,row['run_id'])
            report=get_report(conn,actor_id=actor,case_id=case_id,version=version)
            if report is None:
                raise HTTPException(404,'报告当前不可访问。')
            permitted=conn.execute('''SELECT 1 FROM actors ac JOIN actor_subject_access a USING(actor_id)
                JOIN cases c ON c.subject_id=a.subject_id WHERE ac.actor_id=%s AND ac.active=true
                AND a.can_read_case=true AND c.case_id=%s FOR SHARE OF ac,a''',(actor,case_id)).fetchone()
            if not permitted:
                raise HTTPException(404,'报告当前不可访问。')
            run=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE run_id=%s',(row['run_id'],)).fetchone()
            try:
                check_report_refs(conn,run,report.memory_refs,lock=True)
            except ValueError:
                raise HTTPException(409,'报告引用的历史来源或授权已变化，请重新生成。') from None
            items=((run.get('context_snapshot') or {}).get('memory') or {}).get('items',[])
            return {'report_id':report.report_id,'report_version':version,
                'sources':[{**item,'source_ref':source_key(item)} for item in items]}

    @app.patch('/v1/me/members/{subject_id}/memory-settings', response_model=MemorySettingsResponse)
    def patch_settings(subject_id: UUID, body: MemoryConsentChange,
                       idempotency_key: str = Header(min_length=1, max_length=128),
                       actor=Depends(current_actor), conn=Depends(database)):
        return store.change_settings(conn, actor, subject_id, body, idempotency_key)

    @app.get('/v1/me/members/{subject_id}/memories', response_model=MemoryListResponse)
    def get_memories(subject_id: UUID, actor=Depends(current_actor), conn=Depends(database)):
        result = store.list_memories(conn, actor, subject_id)
        return MemoryListResponse(memories=[public(MemoryItemResponse, row) for row in result['memories']],
                                  candidates=[public(MemoryCandidateResponse, row) for row in result['candidates']])

    @app.post('/v1/me/members/{subject_id}/memory-candidates', response_model=MemoryCandidateResponse, status_code=201)
    def post_candidate(subject_id: UUID, body: MemoryCandidateCreate, actor=Depends(current_actor), conn=Depends(database)):
        require_manual_mode()
        return public(MemoryCandidateResponse, store.create_candidate(conn, actor, subject_id, body))

    @app.post('/v1/me/members/{subject_id}/memory-candidates/{candidate_id}/confirm')
    def confirm(subject_id: UUID, candidate_id: UUID, body: MemoryConfirm,
                idempotency_key: str = Header(min_length=1, max_length=128),
                actor=Depends(current_actor), conn=Depends(database)):
        require_manual_mode()
        return store.confirm_candidate(conn, actor, subject_id, candidate_id, body, idempotency_key)

    @app.delete('/v1/me/members/{subject_id}/memory-candidates/{candidate_id}')
    def dismiss(subject_id: UUID, candidate_id: UUID, body: MemoryRevoke,
                actor=Depends(current_actor), conn=Depends(database)):
        with conn.transaction():
            store.require_member(conn, actor, subject_id)
            store.lock_scope(conn, actor, subject_id)
            row = conn.execute('SELECT version,status FROM care_memory_candidates WHERE candidate_id=%s AND actor_id=%s AND subject_id=%s',
                               (candidate_id, actor, subject_id)).fetchone()
            if not row:
                raise store.AccessDenied()
            if row['version'] != body.expected_version or row['status'] != 'pending':
                raise HTTPException(409, '候选已变化，请刷新后重试。')
            conn.execute("UPDATE care_memory_candidates SET status='dismissed',version=version+1 WHERE candidate_id=%s", (candidate_id,))
            return {'status': 'dismissed'}

    @app.delete('/v1/me/members/{subject_id}/memories/{memory_id}')
    def revoke(subject_id: UUID, memory_id: UUID, body: MemoryRevoke,
               actor=Depends(current_actor), conn=Depends(database)):
        return store.revoke_memory(conn, actor, subject_id, memory_id, body.expected_version)

    @app.get('/v1/conversations/{conversation_id}/memory-settings', response_model=ConversationMemoryResponse)
    def get_conversation_settings(conversation_id: UUID, actor=Depends(current_actor), conn=Depends(database)):
        return store.conversation_settings(conn, actor, conversation_id)

    @app.patch('/v1/conversations/{conversation_id}/memory-settings', response_model=ConversationMemoryResponse)
    def patch_conversation_settings(conversation_id: UUID, body: ConversationMemoryChange,
                                   actor=Depends(current_actor), conn=Depends(database)):
        return store.change_conversation_settings(conn, actor, conversation_id, body)
