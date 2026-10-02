"""Authorized care cases, document analysis, review and persistent agent conversations."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Path as ApiPath, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from .contracts.core import (
    AnalysisRun, Case, Contract, DataOrigin, Document, DocumentVersionRef,
    Evidence, EventBundle, ExternalRef, ExtractedFact, Insight,
    Report, ReviewCorrection, ReviewDecision, ReviewTask,
)
from .repository import (
    AccessDenied, IdempotencyConflict, actor_for_token, connect, create_case,
    create_analysis_run, get_analysis_run, get_case, get_document, get_evidence, get_events, get_facts,
    get_insights, get_report,
    register_document,
)
from .review_repository import (
    ReviewAccessDenied, ReviewNotFound, StaleReview, decide_review, list_reviews,
)
from .care_assistant import AssistantAnswer, answer_question
from . import conversation_repository as chats
from .conversation_agent import CareTools, run_agent

app = FastAPI(title="众安·暖愈智护", version="0.1.0")


@app.exception_handler(HTTPException)
async def business_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        401: "AUTHENTICATION_REQUIRED", 403: "OPERATION_NOT_ALLOWED",
        404: "NOT_FOUND", 409: "IDEMPOTENCY_CONFLICT",
        413: "DOCUMENT_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE",
        503: "DEPENDENCY_UNAVAILABLE",
    }.get(exc.status_code, "REQUEST_FAILED")
    return JSONResponse(status_code=exc.status_code, content={
        "code": code, "message": str(exc.detail), "retryable": exc.status_code == 503,
        "trace_id": str(uuid4()),
    })


@app.exception_handler(RequestValidationError)
async def schema_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "code": "SCHEMA_VALIDATION_FAILED",
        "message": "Request schema validation failed",
        "retryable": False,
        "trace_id": str(uuid4()),
    })


class CreateCase(Contract):
    subject_id: UUID
    consent_id: UUID
    source_ref: str = Field(min_length=1)
    external_case_ref: ExternalRef | None = None
    user_context: dict | None = None
    data_origin: DataOrigin


class CreateRun(Contract):
    document_versions: list[DocumentVersionRef] = Field(min_length=1, max_length=100)
    pipeline_version: str = Field(min_length=1, max_length=100)
    force_new: bool = False


class DecideReview(Contract):
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "correct", "reject"]
    reason: str = Field(min_length=1, max_length=2000)
    corrections: list[ReviewCorrection] = Field(default_factory=list, max_length=20)


class AskAssistant(Contract):
    question: str = Field(min_length=1, max_length=1000)
    report_version: int = Field(ge=1)


class NewConversation(Contract):
    conversation_id: UUID
    case_id: UUID | None = None
    subject_id: UUID | None = None
    recall_enabled: bool = True


class ChatMessage(Contract):
    request_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=20)


class RecallSetting(Contract):
    enabled: bool


DOCUMENT_POLICY_VERSION = "document-policy-v1"
ALLOWED_MEDIA_TYPES = {"application/pdf", "image/jpeg", "image/png", "text/plain"}
DEFAULT_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def document_storage_root() -> Path:
    configured = os.getenv("ZHONGAN_STORAGE_ROOT")
    if not configured:
        raise HTTPException(status_code=503, detail="Document storage is not configured")
    root = Path(configured).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=503, detail="Document storage is unavailable")
    return root


def document_size_limit() -> int:
    try:
        value = int(os.getenv("ZHONGAN_MAX_DOCUMENT_BYTES", str(DEFAULT_MAX_DOCUMENT_BYTES)))
    except ValueError:
        raise HTTPException(status_code=503, detail="Document size policy is invalid") from None
    if value <= 0:
        raise HTTPException(status_code=503, detail="Document size policy is invalid")
    return value


def validate_file_signature(path: Path, media_type: str) -> None:
    with path.open("rb") as handle:
        prefix = handle.read(8)
    valid = {
        "application/pdf": prefix.startswith(b"%PDF-"),
        "image/png": prefix.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": prefix.startswith(b"\xff\xd8\xff"),
    }
    if media_type in valid and not valid[media_type]:
        raise HTTPException(status_code=415, detail="File content does not match declared media type")
    if media_type == "text/plain":
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="Controlled text input must be UTF-8") from None


def database():
    dsn = os.getenv("ZHONGAN_DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Database is not configured")
    try:
        with connect(dsn) as conn:
            yield conn
    except psycopg.OperationalError:
        raise HTTPException(status_code=503, detail="Database is unavailable") from None


def current_actor(authorization: str | None = Header(default=None), conn=Depends(database)) -> UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.removeprefix("Bearer ")
    if not token or len(token) > 4096:
        raise HTTPException(status_code=401, detail="Authentication required")
    actor_id = actor_for_token(conn, token)
    if actor_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return actor_id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scope": "conversation_agent_v1"}


@app.post("/v1/cases", response_model=Case, status_code=201)
def post_case(body: CreateCase, response: Response,
              idempotency_key: str = Header(min_length=1, max_length=128),
              actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> Case:
    if body.data_origin != DataOrigin.synthetic:
        raise HTTPException(status_code=403, detail="Only synthetic imports are enabled")
    try:
        case, created = create_case(
            conn, actor_id=actor_id, subject_id=body.subject_id,
            consent_id=body.consent_id, source_ref=body.source_ref,
            external_case_ref=body.external_case_ref,
            user_context=body.user_context, data_origin=body.data_origin,
            idempotency_key=idempotency_key,
        )
    except AccessDenied:
        raise HTTPException(status_code=404, detail="Authorized subject or consent not found") from None
    except IdempotencyConflict:
        raise HTTPException(status_code=409, detail="Idempotency key reused with different request") from None
    if not created:
        response.status_code = 200
    return case


@app.get("/v1/cases/{case_id}", response_model=Case)
def read_case(case_id: UUID, actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> Case:
    case = get_case(conn, actor_id=actor_id, case_id=case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/v1/cases/{case_id}/documents", response_model=Document, status_code=201)
async def post_document(
    case_id: UUID,
    response: Response,
    file: Annotated[UploadFile, File()],
    source_ref: Annotated[str, Form(min_length=1, max_length=512)],
    document_type: Annotated[str | None, Form(max_length=100)] = None,
    actor_id: UUID = Depends(current_actor),
    conn=Depends(database),
    storage_root: Path = Depends(document_storage_root),
) -> Document:
    media_type = (file.content_type or "").lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Supported types are PDF, JPEG, PNG and UTF-8 text")
    limit = document_size_limit()
    temp_root = storage_root / ".tmp"
    temp_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix="upload-", dir=temp_root)
    os.close(descriptor)
    temp_path = Path(temp_name)
    byte_size = 0
    digest = hashlib.sha256()
    try:
        with temp_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                byte_size += len(chunk)
                if byte_size > limit:
                    raise HTTPException(status_code=413, detail=f"Document exceeds {limit} byte policy limit")
                digest.update(chunk)
                output.write(chunk)
        if byte_size == 0:
            raise HTTPException(status_code=422, detail="Document is empty")
        validate_file_signature(temp_path, media_type)
        page_count = 1 if media_type.startswith("image/") else None
        try:
            document, created = register_document(
                conn, actor_id=actor_id, case_id=case_id,
                document_type=document_type, media_type=media_type,
                byte_size=byte_size, page_count=page_count,
                source_hash=digest.hexdigest(), source_ref=source_ref,
                policy_version=DOCUMENT_POLICY_VERSION, temp_path=temp_path,
                storage_root=storage_root,
            )
        except AccessDenied:
            raise HTTPException(status_code=404, detail="Case not found") from None
        if not created:
            response.status_code = 200
        return document
    finally:
        await file.close()
        if temp_path.exists():
            temp_path.unlink()


@app.get("/v1/cases/{case_id}/documents/{document_id}/content", response_class=FileResponse)
def read_document_content(
    case_id: UUID,
    document_id: UUID,
    version: Annotated[int | None, Query(ge=1)] = None,
    actor_id: UUID = Depends(current_actor),
    conn=Depends(database),
    storage_root: Path = Depends(document_storage_root),
):
    found = get_document(conn, actor_id=actor_id, case_id=case_id,
                         document_id=document_id, version=version)
    if found is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, storage_ref = found
    path = Path(storage_ref).resolve()
    try:
        path.relative_to(storage_root)
    except ValueError:
        raise HTTPException(status_code=503, detail="Document storage reference is invalid") from None
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Document content is unavailable")
    return FileResponse(path, media_type=document.media_type,
                        filename=f"{document.document_id}.bin")


@app.post("/v1/cases/{case_id}/runs", response_model=AnalysisRun, status_code=202)
def post_run(body: CreateRun, case_id: UUID, response: Response,
             actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> AnalysisRun:
    if body.pipeline_version not in {"text-parser-v1", "document-parser-v1"}:
        raise HTTPException(status_code=422, detail="Unsupported pipeline version")
    try:
        run, created = create_analysis_run(
            conn, actor_id=actor_id, case_id=case_id,
            document_versions=body.document_versions,
            pipeline_version=body.pipeline_version, force_new=body.force_new,
        )
    except (AccessDenied, ValueError):
        raise HTTPException(status_code=404, detail="Authorized document version not found") from None
    if not created:
        response.status_code = 200
    return run


@app.get("/v1/runs/{run_id}", response_model=AnalysisRun)
def read_run(run_id: UUID, actor_id: UUID = Depends(current_actor),
             conn=Depends(database)) -> AnalysisRun:
    run = get_analysis_run(conn, actor_id=actor_id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/v1/evidence/{evidence_id}", response_model=Evidence)
def read_evidence(evidence_id: UUID, actor_id: UUID = Depends(current_actor),
                  conn=Depends(database)) -> Evidence:
    item = get_evidence(conn, actor_id=actor_id, evidence_id=evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return item


@app.get("/v1/cases/{case_id}/facts", response_model=list[ExtractedFact])
def read_facts(case_id: UUID, run_id: UUID = Query(),
               actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> list[ExtractedFact]:
    facts = get_facts(conn, actor_id=actor_id, case_id=case_id, run_id=run_id)
    if facts is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return facts


@app.get("/v1/cases/{case_id}/events", response_model=EventBundle)
def read_events(case_id: UUID, run_id: UUID = Query(),
                actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> EventBundle:
    bundle = get_events(conn, actor_id=actor_id, case_id=case_id, run_id=run_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return bundle


@app.get("/v1/cases/{case_id}/insights", response_model=list[Insight])
def read_insights(case_id: UUID, run_id: UUID = Query(),
                  actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> list[Insight]:
    items = get_insights(conn, actor_id=actor_id, case_id=case_id, run_id=run_id)
    if items is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return items


@app.get("/v1/reviews", response_model=list[ReviewTask])
def read_reviews(status: Literal["pending", "decided", "cancelled"] = "pending",
                 limit: Annotated[int, Query(ge=1, le=100)] = 20,
                 cursor: UUID | None = None,
                 actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> list[ReviewTask]:
    try:
        return list_reviews(conn, actor_id=actor_id, status=status, limit=limit, cursor=cursor)
    except ReviewAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer role required") from None


@app.post("/v1/reviews/{review_id}/decision", response_model=ReviewDecision)
def post_review_decision(review_id: UUID, body: DecideReview,
                         idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
                         actor_id: UUID = Depends(current_actor),
                         conn=Depends(database)) -> ReviewDecision:
    try:
        return decide_review(conn, actor_id=actor_id, review_id=review_id,
                             expected_version=body.expected_version,
                             decision=body.decision, reason=body.reason,
                             corrections=body.corrections, idempotency_key=idempotency_key)
    except ReviewNotFound:
        raise HTTPException(status_code=404, detail="Review not found") from None
    except ReviewAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer role required") from None
    except StaleReview:
        raise HTTPException(status_code=409, detail="Review target has a newer version or is already decided") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/v1/cases/{case_id}/reports/{version}", response_model=Report)
def read_report(case_id: UUID, version: Annotated[int, ApiPath(ge=1)],
                actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> Report:
    report = get_report(conn, actor_id=actor_id, case_id=case_id, version=version)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.post("/v1/cases/{case_id}/assistant/messages", response_model=AssistantAnswer)
def post_assistant_message(body: AskAssistant, case_id: UUID,
                           actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> AssistantAnswer:
    report = get_report(conn, actor_id=actor_id, case_id=case_id, version=body.report_version)
    if report is None:
        raise HTTPException(status_code=404, detail="Published report not found")
    try:
        return answer_question(report, body.question)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Care assistant is temporarily unavailable") from None


@app.exception_handler(AccessDenied)
async def chat_access_error(request: Request, exc: AccessDenied):
    return await business_error(request, HTTPException(404, '对话或材料不可访问'))


@app.exception_handler(IdempotencyConflict)
async def chat_conflict_error(request: Request, exc: IdempotencyConflict):
    return await business_error(request, HTTPException(409, '请求标识已用于不同内容'))


@app.exception_handler(chats.TurnBusy)
async def chat_busy_error(request: Request, exc: chats.TurnBusy):
    return await business_error(request, HTTPException(409, '上一条消息仍在处理，请稍后查看或重试'))


@app.get('/v1/chat/subjects')
def chat_subjects(actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    return chats.available_subjects(conn, actor_id)


@app.get('/v1/conversations')
def conversations(actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    return chats.list_conversations(conn, actor_id)


@app.post('/v1/conversations', status_code=201)
def new_conversation(body: NewConversation, actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    try:
        return chats.create_conversation(conn, actor_id, body.conversation_id,
            body.case_id, body.subject_id, body.recall_enabled)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.get('/v1/conversations/{conversation_id}')
def conversation_detail(conversation_id: UUID, actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    conversation = chats.require_conversation(conn, actor_id, conversation_id)
    tools = CareTools(conn, actor_id, conversation_id)
    return {'conversation': conversation, 'turns': chats.get_turns(conn, actor_id, conversation_id),
            'analysis': tools.execute('analysis_status', '{}'),
            'report': tools.execute('read_report', '{}')}


@app.get('/v1/conversations/{conversation_id}/turns')
def conversation_history(conversation_id: UUID, before: UUID | None = None,
                         actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    return chats.get_turns(conn, actor_id, conversation_id, before)


@app.patch('/v1/conversations/{conversation_id}/recall')
def conversation_recall(conversation_id: UUID, body: RecallSetting,
                        actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    chats.require_conversation(conn, actor_id, conversation_id)
    conn.execute('UPDATE conversations SET recall_enabled=%s WHERE conversation_id=%s', (body.enabled, conversation_id))
    return {'recall_enabled': body.enabled}


@app.post('/v1/conversations/{conversation_id}/documents', response_model=Document, status_code=201)
async def chat_upload(conversation_id: UUID, response: Response, file: Annotated[UploadFile, File()],
                      actor_id: UUID = Depends(current_actor), conn=Depends(database),
                      storage_root: Path = Depends(document_storage_root)):
    conversation = chats.require_conversation(conn, actor_id, conversation_id)
    # File names are untrusted metadata, never used as storage paths.
    name = (file.filename or '上传材料').replace('\\', '/').rsplit('/', 1)[-1][:200]
    return await post_document(case_id=conversation['case_id'], response=response, file=file,
        source_ref=name, document_type=None, actor_id=actor_id, conn=conn, storage_root=storage_root)


@app.post('/v1/conversations/{conversation_id}/messages')
def chat_message(conversation_id: UUID, body: ChatMessage,
                 actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    return process_chat_message(conversation_id, body, actor_id, conn)


def process_chat_message(conversation_id, body, actor_id, conn, input_kind='user'):
    question = body.message.strip()
    if not question:
        raise HTTPException(422, '消息不能为空')
    turn = chats.begin_turn(conn, actor_id, conversation_id, body.request_id, question, body.document_ids, input_kind)
    # Persist the input before a slow provider call; interrupted turns can be retried with the same ID.
    conn.commit()
    if turn['status'] == 'completed':
        return {'turn_id': turn['turn_id'], 'answer': turn['answer'], 'tool_events': turn['tool_events']}
    history = [t for t in chats.get_turns(conn, actor_id, conversation_id) if t['turn_id'] != turn['turn_id']]
    tools = CareTools(conn, actor_id, conversation_id)
    events = []

    def progress(current_events):
        events[:] = current_events
        chats.require_conversation(conn, actor_id, conversation_id)
        conn.execute('''UPDATE conversation_turns SET tool_events=%s::jsonb
            WHERE turn_id=%s AND lease_token=%s AND status='running' ''',
            (json.dumps(events), turn['turn_id'], turn['lease_token']))
        conn.commit()

    try:
        answer, events = run_agent(history, question, turn['attachments'], tools, on_event=progress)
        chats.finish_turn(conn, actor_id, conversation_id, turn, answer=answer, events=events)
        conn.commit()
        return {'turn_id': turn['turn_id'], 'answer': answer, 'tool_events': events}
    except (RuntimeError, ValueError, KeyError, TypeError, requests.RequestException) as exc:
        # Log only safe classifications, never provider bodies, prompts or credentials.
        import logging
        provider_response = getattr(exc, 'response', None)
        logging.getLogger(__name__).warning('Chat generation failed: type=%s provider_status=%s',
            type(exc).__name__, getattr(provider_response, 'status_code', None))
        chats.finish_turn(conn, actor_id, conversation_id, turn, events=events, error='AGENT_UNAVAILABLE')
        conn.commit()
        raise HTTPException(503, '暂时无法完成回答，消息已保存，可以重试。') from None


@app.post('/v1/conversations/{conversation_id}/analyses/{run_id}/continue')
def continue_analysis(conversation_id: UUID, run_id: UUID,
                      actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    conversation = chats.require_conversation(conn, actor_id, conversation_id)
    run = get_analysis_run(conn, actor_id=actor_id, run_id=run_id)
    if not run or run.case_id != conversation['case_id']:
        raise HTTPException(404, '分析任务不存在')
    if run.status not in ('completed', 'waiting_review'):
        raise HTTPException(409, '分析尚未完成')
    initiated = conn.execute('''SELECT 1 FROM conversation_turns WHERE conversation_id=%s
        AND status='completed' AND tool_events @> %s::jsonb LIMIT 1''',
        (conversation_id, json.dumps([{'tool': 'start_analysis', 'run_id': str(run_id)}]))).fetchone()
    if not initiated:
        raise HTTPException(409, '此任务不是在当前对话中发起的')
    latest = conn.execute('''SELECT run_id FROM analysis_runs WHERE case_id=%s
        ORDER BY created_at DESC,run_id DESC LIMIT 1''', (run.case_id,)).fetchone()
    if latest['run_id'] != run_id:
        raise HTTPException(409, '已有更新的分析任务')
    request_id = uuid5(NAMESPACE_URL, f'zhongan:analysis-continuation:{conversation_id}:{run_id}')
    return process_chat_message(conversation_id, ChatMessage(request_id=request_id,
        message='材料分析已结束，请结合我刚才关注的问题，读取本次材料和可用报告继续解释；待复核内容请明确说明。'),
        actor_id=actor_id, conn=conn, input_kind='analysis_ready')
