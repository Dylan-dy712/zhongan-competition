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
from starlette.concurrency import run_in_threadpool
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
from .release_repository import publish_report
from .quality_export import (MappingCreate, SnapshotBuild, attach_case_attribution,
    create_entity_mapping, draft_policy, export_quality_input, list_entity_mappings,
    list_snapshots, load_snapshot, persist_snapshot, recommend_from_latest, require_reviewer)
from .quality_profiles import ProfileMatchRequest
from .delivery_repository import (list_deliveries, record_receipt, submit_feedback, list_feedback_triage,
    resolve_feedback, FeedbackNotFound, FeedbackAccessDenied, StaleFeedback)
from .care_assistant import AssistantAnswer, answer_question
from . import conversation_repository as chats
from .conversation_agent import CareTools, run_agent, ANALYSIS_PROMPT_VERSION
from .material_report import get_material_report
from . import accounts
from .document_quality import inspect_photo
from .ocr import create_ocr
from . import medical_records

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


class AttributionCreate(Contract):
    run_id: UUID
    entity_id: UUID
    evidence_ids: list[UUID]


class ResolveFeedback(Contract):
    resolution_reason: str = Field(min_length=1, max_length=2000)


class DecideReview(Contract):
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "correct", "reject"]
    reason: str = Field(min_length=1, max_length=2000)
    corrections: list[ReviewCorrection] = Field(default_factory=list, max_length=20)


class PublishReport(Contract):
    expected_version: int = Field(ge=1)


class DeliveryReceipt(Contract):
    state: Literal['presented','read']
    expected_version: int = Field(ge=0)


class SubmitFeedback(Contract):
    report_id: UUID
    report_version: int = Field(ge=1)
    action_id: UUID | None = None
    type: Literal['helpful','not_helpful','inaccurate','needs_help']
    text: str | None = Field(default=None,min_length=1,max_length=4000)


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
    document_ids: list[UUID] = Field(default_factory=list)
    attachment_ids: list[UUID] = Field(default_factory=list)


class AnalysisRequest(ChatMessage):
    force_new: bool = False


class ChatAttachment(Contract):
    attachment_id: UUID
    name: str
    media_type: str
    byte_size: int


class RecallSetting(Contract):
    enabled: bool

class OrganizeMedicalRecords(Contract):
    subject_id: UUID

class MedicalRecordAssignment(Contract):
    mode: Literal['join','separate','related']
    target_record_id: UUID | None = None
    expected_version: int = Field(ge=0)


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


@app.post('/v1/auth/register', status_code=201, response_model=accounts.SessionResponse)
def register_account(body: accounts.Registration, request: Request, response: Response, conn=Depends(database)):
    accounts.rate_limit(conn, 'register-ip:'+(request.client.host if request.client else 'unknown'), 10)
    response.headers['Cache-Control'] = 'no-store'
    return accounts.register(conn, body)


@app.post('/v1/auth/login', response_model=accounts.SessionResponse)
def login_account(body: accounts.Credentials, request: Request, response: Response, conn=Depends(database)):
    accounts.rate_limit(conn, 'login-ip:'+(request.client.host if request.client else 'unknown'), 60)
    response.headers['Cache-Control'] = 'no-store'
    return accounts.login(conn, body)


@app.get('/v1/auth/me', response_model=accounts.ProfileResponse)
def account_profile(response: Response, actor_id=Depends(current_actor), conn=Depends(database)):
    response.headers['Cache-Control'] = 'no-store'
    user = conn.execute('SELECT username,display_name FROM user_accounts WHERE actor_id=%s', (actor_id,)).fetchone()
    return {'user': user}


@app.post('/v1/auth/logout', status_code=204)
def logout_account(authorization: str = Header(), actor_id=Depends(current_actor), conn=Depends(database)):
    conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE token_sha256=%s AND actor_id=%s',
                 (accounts.token_digest(authorization.removeprefix('Bearer ')), actor_id))
    return Response(status_code=204)


@app.get('/v1/me/consents', response_model=accounts.ConsentResponse)
def get_account_consent(response: Response, subject_id: UUID | None = None, actor_id=Depends(current_actor), conn=Depends(database)):
    response.headers['Cache-Control'] = 'no-store'
    return accounts.care_consent(conn, actor_id, subject_id)


@app.post('/v1/me/consents', response_model=accounts.ConsentResponse)
def set_account_consent(body: accounts.ConsentChange, idempotency_key: str = Header(min_length=1,max_length=128), subject_id: UUID | None = None, actor_id=Depends(current_actor), conn=Depends(database)):
    return accounts.change_consent(conn, actor_id, body, idempotency_key, subject_id)


@app.get('/v1/me/members', response_model=list[accounts.MemberResponse])
def account_members(response: Response, actor_id=Depends(current_actor), conn=Depends(database)):
    response.headers['Cache-Control'] = 'no-store'
    return accounts.list_members(conn, actor_id)


@app.post('/v1/me/members', status_code=201, response_model=accounts.MemberResponse)
def add_account_member(body: accounts.MemberInput, actor_id=Depends(current_actor), conn=Depends(database)):
    return accounts.save_member(conn, actor_id, body)


@app.patch('/v1/me/members/{subject_id}', response_model=accounts.MemberResponse)
def edit_account_member(subject_id: UUID, body: accounts.MemberInput, actor_id=Depends(current_actor), conn=Depends(database)):
    return accounts.save_member(conn, actor_id, body, subject_id)


@app.post("/v1/cases", response_model=Case, status_code=201)
def post_case(body: CreateCase, response: Response,
              idempotency_key: str = Header(min_length=1, max_length=128),
              actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> Case:
    if body.data_origin != DataOrigin.synthetic:
        from services.judge_demo.app import judge_upload_allowed
        if not judge_upload_allowed(conn, actor_id, body):
            raise HTTPException(status_code=403, detail="Only synthetic imports and approved judge samples are enabled")
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


@app.post('/v1/materials/inspect')
async def inspect_material(file: Annotated[UploadFile, File()], subject_id: Annotated[UUID, Form()],
                           actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    try:
        if not any(str(item['subject_id']) == str(subject_id) for item in chats.available_subjects(conn, actor_id)):
            raise HTTPException(status_code=403, detail='请先确认该人员的资料用途授权。')
        if file.content_type not in {'image/jpeg', 'image/png'}:
            raise HTTPException(status_code=415, detail='照片检查支持 JPG 或 PNG。')
        data = await file.read(document_size_limit() + 1)
        if not data or len(data) > document_size_limit():
            raise HTTPException(status_code=413, detail='请选择非空且不超过 10 MB 的图片。')
        try:
            result = await run_in_threadpool(inspect_photo, data, create_ocr)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail='图片无法读取，请重新选择有效图片。') from exc
        # Consent can be withdrawn while OCR is in flight.
        if not any(str(item['subject_id']) == str(subject_id) for item in chats.available_subjects(conn, actor_id)):
            raise HTTPException(status_code=403, detail='资料授权已变更，请重新确认。')
        return result
    finally:
        await file.close()


@app.get('/v1/knowledge/{entry_id}')
def read_knowledge_source(entry_id: str, actor_id: UUID = Depends(current_actor)):
    from .knowledge_retrieval import KnowledgeRetriever
    if entry_id.startswith('WEB-VOLC-'):
        from .web_knowledge import WebKnowledge
        item=WebKnowledge().resolve(entry_id)
        if not item:raise HTTPException(status_code=404,detail='该网络参考资料已过期或暂不可用。')
        return item
    retriever = KnowledgeRetriever()
    item = retriever.by_id.get(entry_id)
    if not item:
        raise HTTPException(status_code=404, detail='该参考资料暂不可用。')
    return {key: item.get(key, '') for key in ('entry_id', 'title', 'source', 'scope', 'content')} | {'version': retriever.version}


@app.post("/v1/cases/{case_id}/documents", response_model=Document, status_code=201)
async def post_document(
    case_id: UUID,
    response: Response,
    file: Annotated[UploadFile, File()],
    source_ref: Annotated[str, Form(min_length=1, max_length=512)],
    document_type: Annotated[str | None, Form(max_length=100)] = None,
    replaces_document_id: Annotated[UUID | None, Form()] = None,
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
        sample_case = get_case(conn, actor_id=actor_id, case_id=case_id)
        if sample_case and sample_case.data_origin==DataOrigin.official_deidentified and (sample_case.user_context or {}).get('judge_demo'):
            from services.judge_demo.app import verify_sample_upload
            verify_sample_upload(conn, actor_id, sample_case, digest.hexdigest())
        page_count = 1 if media_type.startswith("image/") else None
        try:
            document, created = register_document(
                conn, actor_id=actor_id, case_id=case_id,
                document_type=document_type, media_type=media_type,
                byte_size=byte_size, page_count=page_count,
                source_hash=digest.hexdigest(), source_ref=source_ref,
                policy_version=DOCUMENT_POLICY_VERSION, temp_path=temp_path,
                storage_root=storage_root,
                replaces_document_id=replaces_document_id,
            )
        except AccessDenied:
            raise HTTPException(status_code=404, detail="Case not found") from None
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
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


@app.get('/v1/cases/{case_id}/material-quality')
def read_material_quality(case_id: UUID, run_id: UUID = Query(), actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    run = get_analysis_run(conn, actor_id=actor_id, run_id=run_id)
    if run is None or run.case_id != case_id:
        raise HTTPException(status_code=404, detail='Run not found')
    rows = conn.execute('''SELECT d.document_id,d.source_ref AS name,p.page_index,
           p.structure_metadata->'photo_quality' AS quality
        FROM analysis_runs r CROSS JOIN LATERAL jsonb_array_elements(r.document_versions) v
        JOIN documents d ON d.document_id=(v->>'document_id')::uuid
        JOIN document_pages p ON p.document_id=d.document_id AND p.document_version=(v->>'document_version')::integer
        WHERE r.run_id=%s AND r.case_id=%s AND p.structure_metadata ? 'photo_quality'
        ORDER BY d.document_id,p.page_index''',(run_id,case_id)).fetchall()
    return [dict(row) for row in rows]


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


@app.post('/v1/cases/{case_id}/reports/{version}/publish')
def post_report_release(case_id: UUID, version: Annotated[int, ApiPath(ge=1)], body: PublishReport,
                        idempotency_key: Annotated[str, Header(min_length=1,max_length=200)],
                        actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    try:
        return publish_report(conn,actor_id=actor_id,case_id=case_id,version=version,
                              expected_version=body.expected_version,idempotency_key=idempotency_key)
    except ReviewNotFound:
        raise HTTPException(404,'Authorized report not found') from None
    except ReviewAccessDenied:
        raise HTTPException(403,'Medical reviewer role required') from None
    except StaleReview:
        raise HTTPException(409,'Report version or request conflicts') from None
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    except OSError:
        raise HTTPException(503,'Report knowledge validation unavailable') from None


@app.get("/v1/quality/entity-mappings")
def get_entity_mappings(actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> list[dict]:
    try:
        return list_entity_mappings(conn)
    except ReviewAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer role required") from None


@app.post("/v1/quality/entity-mappings", status_code=200)
def post_entity_mapping(body: MappingCreate, actor_id: UUID = Depends(current_actor),
                        conn=Depends(database)) -> dict:
    try:
        return create_entity_mapping(conn, actor_id=actor_id, body=body)
    except ReviewAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer role required") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/v1/quality/cases/{case_id}/attribution")
def post_case_attribution(case_id: UUID, body: AttributionCreate,
                          actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> dict:
    try:
        return attach_case_attribution(conn, actor_id=actor_id, case_id=case_id,
            run_id=body.run_id, entity_id=body.entity_id, evidence_ids=body.evidence_ids)
    except ReviewAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer role required") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/v1/quality/snapshots/build")
def post_quality_snapshot_build(body: SnapshotBuild, actor_id: UUID = Depends(current_actor),
                                conn=Depends(database)) -> dict:
    try:
        require_reviewer(conn, actor_id)
        dataset_version = body.dataset_version or (
            "business-db@" + conn.execute("SELECT coalesce(max(created_at)::date::text,'none') AS d FROM analysis_runs").fetchone()["d"])
        policy = draft_policy(body.window_start, body.window_end,
                              min_sample_size=body.min_sample_size, max_missing_rate=body.max_missing_rate)
        data, limitations = export_quality_input(conn, policy=policy, dataset_version=dataset_version)
        if data is None:
            raise HTTPException(status_code=422, detail="; ".join(limitations) or "no authoritative records")
        result = persist_snapshot(conn, data=data, actor_id=actor_id, limitations=limitations)
        return {"snapshot_id": str(result["snapshot_id"]), "dataset_version": data.dataset_version,
                "included_records": result["included_records"], "profile_count": len(result["profiles"]),
                "limitations": limitations, "created": result["created"]}
    except ReviewAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer role required") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post('/v1/feedback/{feedback_id}/resolve')
def post_feedback_resolution(feedback_id: UUID, body: ResolveFeedback,
                             actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> dict:
    try:
        return resolve_feedback(conn, actor_id=actor_id, feedback_id=feedback_id,
                                resolution_reason=body.resolution_reason)
    except FeedbackNotFound:
        raise HTTPException(status_code=404, detail="Feedback not found") from None
    except FeedbackAccessDenied:
        raise HTTPException(status_code=403, detail="Medical reviewer or customer service role required") from None
    except StaleFeedback:
        raise HTTPException(status_code=409, detail="Feedback is not pending or has already been resolved") from None


@app.get('/v1/quality/demo')
def quality_demo_snapshot(actor_id: UUID = Depends(current_actor)):
    from .quality_demo import demo_snapshot
    return demo_snapshot()


@app.post('/v1/quality/demo/recommendations')
def quality_demo_match(body: ProfileMatchRequest, actor_id: UUID = Depends(current_actor)):
    from .quality_demo import demo_recommendations
    return demo_recommendations(body)


@app.post("/v1/quality/recommendations")
def post_quality_recommendations(body: ProfileMatchRequest,
                                 actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> dict:
    item = recommend_from_latest(conn, body)
    if item is None:
        raise HTTPException(status_code=404, detail="No quality snapshot has been built yet")
    return item


@app.get("/v1/quality/snapshots")
def get_quality_snapshots(actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> list[dict]:
    return list_snapshots(conn)


@app.get("/v1/quality/snapshots/{snapshot_id}")
def get_quality_snapshot(snapshot_id: UUID, actor_id: UUID = Depends(current_actor),
                         conn=Depends(database)) -> dict:
    item = load_snapshot(conn, snapshot_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return item


@app.post("/v1/cases/{case_id}/assistant/messages", response_model=AssistantAnswer)
def post_assistant_message(body: AskAssistant, case_id: UUID,
                           actor_id: UUID = Depends(current_actor), conn=Depends(database)) -> AssistantAnswer:
    report = get_report(conn, actor_id=actor_id, case_id=case_id, version=body.report_version, patient_view=True)
    if report is None:
        raise HTTPException(status_code=404, detail="Published report not found")
    try:
        return answer_question(report, body.question)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Care assistant is temporarily unavailable") from None


@app.get('/v1/cases/{case_id}/deliveries')
def get_app_deliveries(case_id: UUID, limit: Annotated[int,Query(ge=1,le=100)]=20,
                       actor_id: UUID=Depends(current_actor), conn=Depends(database)):
    return list_deliveries(conn,actor_id=actor_id,case_id=case_id,limit=limit)


@app.post('/v1/deliveries/{outbox_id}/receipts')
def post_app_receipt(outbox_id: UUID, body: DeliveryReceipt,
                     idempotency_key: Annotated[str,Header(min_length=1,max_length=200)],
                     actor_id: UUID=Depends(current_actor), conn=Depends(database)):
    return record_receipt(conn,actor_id=actor_id,outbox_id=outbox_id,state=body.state,
                          expected_version=body.expected_version,idempotency_key=idempotency_key)


@app.post('/v1/feedback',status_code=201)
def post_care_feedback(body: SubmitFeedback,
                       idempotency_key: Annotated[str,Header(min_length=1,max_length=200)],
                       actor_id: UUID=Depends(current_actor), conn=Depends(database)):
    return submit_feedback(conn,actor_id=actor_id,idempotency_key=idempotency_key,**body.model_dump())


@app.get('/v1/feedback/triage')
def get_care_feedback_triage(limit: Annotated[int,Query(ge=1,le=100)]=20,
                             actor_id: UUID=Depends(current_actor), conn=Depends(database)):
    return list_feedback_triage(conn,actor_id=actor_id,limit=limit)


@app.exception_handler(ReviewNotFound)
async def care_not_found(request: Request, exc: ReviewNotFound):
    return await business_error(request,HTTPException(404,'关怀记录不可访问'))


@app.exception_handler(ReviewAccessDenied)
async def care_role_denied(request: Request, exc: ReviewAccessDenied):
    return await business_error(request,HTTPException(403,'当前身份不能执行此操作'))


@app.exception_handler(StaleReview)
async def care_stale_request(request: Request, exc: StaleReview):
    return await business_error(request,HTTPException(409,'版本或请求已变化，请刷新后重试'))


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
def conversations(subject_id: UUID | None = None, actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    from .conversation_titles import prepare_list
    return prepare_list(conn, chats.list_conversations(conn, actor_id, subject_id))


@app.get('/v1/medical-records')
def medical_record_list(subject_id:UUID,actor_id:UUID=Depends(current_actor),conn=Depends(database)):
    return medical_records.list_records(conn,actor_id,subject_id)


@app.post('/v1/medical-records/organize',status_code=202)
def organize_medical_records(body:OrganizeMedicalRecords,actor_id:UUID=Depends(current_actor),conn=Depends(database)):
    return medical_records.organize(conn,actor_id,body.subject_id)


@app.patch('/v1/medical-records/cases/{case_id}')
def change_medical_record(case_id:UUID,body:MedicalRecordAssignment,actor_id:UUID=Depends(current_actor),conn=Depends(database)):
    if body.mode in ('join','related') and not body.target_record_id:raise HTTPException(422,'请选择目标就医记录。')
    try:return medical_records.change_assignment(conn,actor_id,case_id,body.mode,body.target_record_id,body.expected_version)
    except medical_records.StaleRecord:raise HTTPException(409,'记录已更新，请重新加载后再调整。') from None


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
            'report': tools.execute('read_report', '{}'),
            'material_report': get_material_report(conn, actor_id, conversation_id)}


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


@app.patch('/v1/conversations/{conversation_id}/report-context')
def conversation_report_context(conversation_id:UUID,body:RecallSetting,
                                actor_id:UUID=Depends(current_actor),conn=Depends(database)):
    chats.require_conversation(conn,actor_id,conversation_id)
    row=conn.execute("""UPDATE conversations SET report_context_enabled=%s,
        report_context_version=report_context_version+CASE WHEN report_context_enabled<>%s THEN 1 ELSE 0 END
        WHERE conversation_id=%s AND actor_id=%s RETURNING report_context_enabled,report_context_version""",
        (body.enabled,body.enabled,conversation_id,actor_id)).fetchone()
    return row


@app.post('/v1/conversations/{conversation_id}/documents', response_model=Document, status_code=201)
async def chat_upload(conversation_id: UUID, response: Response, file: Annotated[UploadFile, File()],
                      actor_id: UUID = Depends(current_actor), conn=Depends(database),
                      storage_root: Path = Depends(document_storage_root)):
    conversation = chats.require_conversation(conn, actor_id, conversation_id)
    # File names are untrusted metadata, never used as storage paths.
    name = (file.filename or '上传材料').replace('\\', '/').rsplit('/', 1)[-1][:200]
    return await post_document(case_id=conversation['case_id'], response=response, file=file,
        source_ref=name, document_type=None, actor_id=actor_id, conn=conn, storage_root=storage_root)


@app.post('/v1/conversations/{conversation_id}/documents/{document_id}/replacement', response_model=Document, status_code=201)
async def replace_chat_document(conversation_id: UUID, document_id: UUID, response: Response,
                                file: Annotated[UploadFile, File()], actor_id: UUID = Depends(current_actor),
                                conn=Depends(database), storage_root: Path = Depends(document_storage_root)):
    conversation = chats.require_conversation(conn, actor_id, conversation_id)
    name = (file.filename or '重新上传材料').replace('\\', '/').rsplit('/', 1)[-1][:200]
    return await post_document(case_id=conversation['case_id'],response=response,file=file,
        source_ref=name,document_type=None,replaces_document_id=document_id,actor_id=actor_id,
        conn=conn,storage_root=storage_root)


@app.post('/v1/conversations/{conversation_id}/attachments', response_model=ChatAttachment, status_code=201)
async def chat_attachment_upload(conversation_id: UUID, response: Response, file: Annotated[UploadFile, File()],
                                 actor_id: UUID = Depends(current_actor), conn=Depends(database),
                                 storage_root: Path = Depends(document_storage_root)):
    from .chat_attachments import register_attachment
    chats.require_conversation(conn, actor_id, conversation_id)
    media_type = (file.content_type or '').lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(415, '请选择 JPG、PNG、PDF 或 UTF-8 文本。')
    temp_root = storage_root / '.tmp'
    temp_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='chat-', dir=temp_root)
    os.close(descriptor)
    path, digest, size = Path(name), hashlib.sha256(), 0
    limit = document_size_limit()
    try:
        with path.open('wb') as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, '附件超过允许大小，请拆分后发送。')
                output.write(chunk)
                digest.update(chunk)
        if not size:
            raise HTTPException(422, '附件为空，请重新选择。')
        validate_file_signature(path, media_type)
        result, created = register_attachment(conn, actor_id, conversation_id,
            name=(file.filename or '聊天附件').replace('\\', '/').rsplit('/', 1)[-1][:200],
            media_type=media_type, byte_size=size, source_hash=digest.hexdigest(),
            temp_path=path, storage_root=storage_root)
        if not created:
            response.status_code = 200
        return result
    finally:
        await file.close()
        path.unlink(missing_ok=True)


@app.post('/v1/conversations/{conversation_id}/messages')
def chat_message(conversation_id: UUID, body: ChatMessage,
                 actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    return process_chat_message(conversation_id, body, actor_id, conn)


@app.post('/v1/conversations/{conversation_id}/analyses')
def submit_chat_analysis(conversation_id: UUID, body: AnalysisRequest,
                         actor_id: UUID = Depends(current_actor), conn=Depends(database)):
    """Persist the user's request and queue material processing without a model round."""
    if not body.message.strip():
        raise HTTPException(422, '分析请求不能为空')
    if body.attachment_ids:
        raise HTTPException(422, '请通过解读报告入口上传报告材料。')
    turn = chats.begin_turn(conn, actor_id, conversation_id, body.request_id,
                            body.message.strip() + ('\n（重新分析当前材料）' if body.force_new else ''), body.document_ids, 'user')
    conn.commit()
    if turn['status'] == 'completed':
        return {'turn_id': turn['turn_id'], 'answer': turn['answer'], 'tool_events': turn['tool_events']}
    tools = CareTools(conn, actor_id, conversation_id, turn['turn_id'],force_analysis=body.force_new)
    try:
        result = tools.execute('start_analysis', '{}')
        if not result.get('run_id'):
            raise ValueError('NEEDS_MATERIALS')
        events = [{'tool': 'start_analysis', 'status': result['status'], 'run_id': result['run_id']}]
        answer = {'text': '材料已收到，正在分析。完成后会生成材料分析报告，你可以查看依据并继续追问。',
                  'evidence_refs': [], 'history_refs': []}
        chats.finish_turn(conn, actor_id, conversation_id, turn, answer=answer, events=events)
        conn.commit()
        return {'turn_id': turn['turn_id'], 'answer': answer, 'tool_events': events}
    except ValueError:
        chats.finish_turn(conn, actor_id, conversation_id, turn, error='ANALYSIS_SUBMISSION_FAILED')
        conn.commit()
        raise HTTPException(422, '请先上传材料，再开始分析。') from None


def process_chat_message(conversation_id, body, actor_id, conn, input_kind='user', analysis_run_id=None):
    question = body.message.strip()
    if not question:
        raise HTTPException(422, '消息不能为空')
    turn = chats.begin_turn(conn, actor_id, conversation_id, body.request_id, question, body.document_ids, input_kind,
                            attachment_ids=body.attachment_ids)
    # Persist the input before a slow provider call; interrupted turns can be retried with the same ID.
    conn.commit()
    if turn['status'] == 'completed':
        return {'turn_id': turn['turn_id'], 'answer': turn['answer'], 'tool_events': turn['tool_events']}
    if input_kind == 'analysis_ready':
        conn.execute("UPDATE conversation_turns SET lease_expires_at=now()+interval '5 minutes' WHERE turn_id=%s AND lease_token=%s",
                     (turn['turn_id'], turn['lease_token']))
        conn.commit()
    history = [t for t in chats.get_turns(conn, actor_id, conversation_id) if t['turn_id'] != turn['turn_id']]
    tools = CareTools(conn, actor_id, conversation_id,turn['turn_id'])
    tools.allow_analysis = input_kind == 'analysis_ready'
    events = []

    def progress(current_events):
        events[:] = current_events
        chats.require_conversation(conn, actor_id, conversation_id)
        conn.execute('''UPDATE conversation_turns SET tool_events=%s::jsonb,
            lease_expires_at=now()+interval '5 minutes'
            WHERE turn_id=%s AND lease_token=%s AND status='running' ''',
            (json.dumps(events), turn['turn_id'], turn['lease_token']))
        conn.commit()

    try:
        attachment_ids = [item['document_id'] for item in turn['attachments'] if item.get('kind') == 'chat_attachment']
        if attachment_ids:
            from .chat_attachments import read_attachments
            def attachment_progress():
                progress([{'tool': 'read_chat_attachments', 'status': 'running'}])
            tools.message_materials = read_attachments(conn, actor_id, conversation_id, attachment_ids, attachment_progress)
            progress([{'tool': 'read_chat_attachments', 'status': tools.message_materials['status']}])
        answer, events = run_agent(history, question, turn['attachments'], tools, on_event=progress,
                                  analysis_mode=input_kind == 'analysis_ready',
                                  initial_analysis=tools.reusable_analysis() if input_kind == 'analysis_ready' else None)
        if analysis_run_id is not None:
            # Recheck the actual current case and run after slow model generation.
            current = chats.require_conversation(conn, actor_id, conversation_id)
            latest = conn.execute('SELECT run_id FROM analysis_runs WHERE case_id=%s ORDER BY created_at DESC,run_id DESC LIMIT 1',
                                  (current['case_id'],)).fetchone()
            if not latest or latest['run_id'] != analysis_run_id:
                raise ValueError('ANALYSIS_SUPERSEDED')
            documents = conn.execute('SELECT document_id,document_version,source_hash FROM documents WHERE case_id=%s AND NOT EXISTS (SELECT 1 FROM document_replacements replacement WHERE replacement.old_document_id=documents.document_id) ORDER BY document_id',
                                     (current['case_id'],)).fetchall()
            actual = [{**d, 'document_id': str(d['document_id'])} for d in documents]
            # Even an upload that has not queued its new analysis invalidates this draft.
            frozen = conn.execute('SELECT document_versions FROM analysis_runs WHERE run_id=%s',
                                  (analysis_run_id,)).fetchone()['document_versions']
            if actual != sorted(frozen, key=lambda d: d['document_id']):
                raise ValueError('ANALYSIS_MATERIALS_CHANGED')
            answer['analysis_run_id'] = str(analysis_run_id)
        chats.finish_turn(conn, actor_id, conversation_id, turn, answer=answer, events=events)
        conn.commit()
        return {'turn_id': turn['turn_id'], 'answer': answer, 'tool_events': events}
    except (RuntimeError, ValueError, KeyError, TypeError, requests.RequestException) as exc:
        if isinstance(exc, ValueError) and str(exc) in {'ANALYSIS_SUPERSEDED', 'ANALYSIS_MATERIALS_CHANGED'}:
            chats.finish_turn(conn, actor_id, conversation_id, turn, events=events, error='ANALYSIS_SUPERSEDED')
            conn.commit()
            raise HTTPException(409, '材料已更新，新的分析完成后会重新解读。') from None
        # Log only safe classifications, never provider bodies, prompts or credentials.
        import logging
        provider_response = getattr(exc, 'response', None)
        from .generation_errors import generation_error_code
        code = generation_error_code(exc)
        logging.getLogger(__name__).warning('Chat generation failed: type=%s code=%s provider_status=%s',
            type(exc).__name__, code, getattr(provider_response, 'status_code', None))
        chats.finish_turn(conn, actor_id, conversation_id, turn, events=events, error=code)
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
    documents = conn.execute('''SELECT document_id,document_version,source_hash FROM documents
        WHERE case_id=%s AND NOT EXISTS (SELECT 1 FROM document_replacements replacement
        WHERE replacement.old_document_id=documents.document_id) ORDER BY document_id''',
        (run.case_id,)).fetchall()
    frozen = conn.execute('SELECT document_versions FROM analysis_runs WHERE run_id=%s',(run_id,)).fetchone()
    actual = [{**d,'document_id':str(d['document_id'])} for d in documents]
    if actual != sorted(frozen['document_versions'],key=lambda d:d['document_id']):
        raise HTTPException(409,'材料已更新，请先分析最新材料。')
    request_id = uuid5(NAMESPACE_URL, f'zhongan:{ANALYSIS_PROMPT_VERSION}:{conversation_id}:{run_id}')
    return process_chat_message(conversation_id, ChatMessage(request_id=request_id,
        message='请结合本次实际材料和我关注的问题，写一份温和清楚、连贯自然的文字分析，直接在对话里解释；内容重点由材料决定，有不确定的地方就说明。'),
        actor_id=actor_id, conn=conn, input_kind='analysis_ready', analysis_run_id=run_id)
