"""REQ-01/02 API slice. Medical extraction remains unavailable until implemented."""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from .contracts.core import (
    AnalysisRun, Case, Contract, DataOrigin, Document, DocumentVersionRef,
    Evidence, EventBundle, ExternalRef, ExtractedFact, Insight,
)
from .repository import (
    AccessDenied, IdempotencyConflict, actor_for_token, connect, create_case,
    create_analysis_run, get_analysis_run, get_case, get_document, get_evidence, get_events, get_facts,
    get_insights,
    register_document,
)

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
    return {"status": "ok", "scope": "req05_evidence_bound_insights"}


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
