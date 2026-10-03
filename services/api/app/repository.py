"""Authoritative PostgreSQL reads and writes for the REQ-01 slice."""

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from .contracts.core import (
    AnalysisRun, Case, DataOrigin, Document, DocumentVersionRef, Evidence,
    EventBundle, EventRelation, ExecutionMode, ExternalRef, ExtractedFact,
    Insight, MedicalEvent, Report, TextSpan,
)
from .report_builder import POLICY_VERSION
from .review_service import check_report_knowledge
from .report_context import capture_context, context_sources


class AccessDenied(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_digest(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def connect(dsn: str):
    return psycopg.connect(dsn, row_factory=dict_row)


def actor_for_token(conn, token: str) -> UUID | None:
    row = conn.execute(
        "SELECT actor_id FROM actors WHERE token_sha256 = %s AND active = true",
        (token_digest(token),),
    ).fetchone()
    return row["actor_id"] if row else None


def create_case(conn, *, actor_id: UUID, subject_id: UUID, consent_id: UUID,
                source_ref: str, external_case_ref: ExternalRef | None,
                user_context: dict | None, data_origin: DataOrigin,
                idempotency_key: str) -> tuple[Case, bool]:
    payload = {
        "subject_id": str(subject_id), "consent_id": str(consent_id),
        "source_ref": source_ref,
        "external_case_ref": external_case_ref.model_dump() if external_case_ref else None,
        "user_context": user_context, "data_origin": data_origin.value,
    }
    digest = request_digest(payload)
    with conn.transaction():
        # Serialize retries by the trusted actor and supplied key.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{actor_id}:{idempotency_key}",))
        allowed = conn.execute(
            """SELECT 1 FROM actor_subject_access
               WHERE actor_id = %s AND subject_id = %s AND can_create_case = true
               FOR SHARE""",
            (actor_id, subject_id),
        ).fetchone()
        if not allowed:
            raise AccessDenied()
        valid_consent = conn.execute(
            """SELECT 1 FROM consents c JOIN consent_purposes p USING (consent_id)
               WHERE c.consent_id = %s AND c.subject_id = %s
                 AND p.purpose = 'case_guidance' AND p.status = 'active'
                 AND (p.expires_at IS NULL OR p.expires_at > now())
               FOR SHARE OF c, p""",
            (consent_id, subject_id),
        ).fetchone()
        if not valid_consent:
            raise AccessDenied()
        old = conn.execute(
            "SELECT * FROM cases WHERE created_by = %s AND idempotency_key = %s",
            (actor_id, idempotency_key),
        ).fetchone()
        if old:
            if old["request_hash"] != digest:
                raise IdempotencyConflict()
            return _to_case(old), False
        row = conn.execute(
            """INSERT INTO cases (case_id, subject_id, consent_id, created_by,
               source_system, external_case_id, source_ref, user_context,
               data_origin, idempotency_key, request_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
               RETURNING *""",
            (uuid4(), subject_id, consent_id, actor_id,
             external_case_ref.source_system if external_case_ref else None,
             external_case_ref.external_id if external_case_ref else None,
             source_ref, json.dumps(user_context) if user_context is not None else None,
             data_origin.value, idempotency_key, digest),
        ).fetchone()
        return _to_case(row), True


def get_case(conn, *, actor_id: UUID, case_id: UUID) -> Case | None:
    row = conn.execute(
        """SELECT c.* FROM cases c JOIN actor_subject_access a
           ON a.subject_id = c.subject_id AND a.actor_id = %s AND a.can_read_case = true
           JOIN consent_purposes p ON p.consent_id = c.consent_id
             AND p.purpose = 'case_guidance' AND p.status = 'active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE c.case_id = %s""",
        (actor_id, case_id),
    ).fetchone()
    return _to_case(row) if row else None


def register_document(conn, *, actor_id: UUID, case_id: UUID,
                      document_type: str | None, media_type: str,
                      byte_size: int, page_count: int | None,
                      source_hash: str, source_ref: str,
                      policy_version: str, temp_path: Path,
                      storage_root: Path) -> tuple[Document, bool]:
    final_path: Path | None = None
    try:
        with conn.transaction():
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"document:{case_id}:{source_hash}",),
            )
            allowed = conn.execute(
                """SELECT 1 FROM cases c JOIN actor_subject_access a
                   ON a.subject_id = c.subject_id AND a.actor_id = %s
                     AND a.can_create_case = true
                   JOIN consent_purposes p ON p.consent_id = c.consent_id
                     AND p.purpose = 'case_guidance' AND p.status = 'active'
                     AND (p.expires_at IS NULL OR p.expires_at > now())
                   WHERE c.case_id = %s FOR SHARE OF c, a, p""",
                (actor_id, case_id),
            ).fetchone()
            if not allowed:
                raise AccessDenied()
            old = conn.execute(
                "SELECT * FROM documents WHERE case_id = %s AND source_hash = %s",
                (case_id, source_hash),
            ).fetchone()
            if old:
                return _to_document(old), False
            document_id = uuid4()
            final_path = storage_root / str(case_id) / str(document_id) / "1.bin"
            final_path.parent.mkdir(parents=True, exist_ok=False)
            os.replace(temp_path, final_path)
            final_path.chmod(0o600)
            row = conn.execute(
                """INSERT INTO documents
                   (document_id, case_id, document_type, media_type, byte_size,
                    page_count, source_hash, source_ref, storage_ref, status, policy_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                           'registered', %s) RETURNING *""",
                (document_id, case_id, document_type, media_type, byte_size,
                 page_count, source_hash, source_ref, str(final_path), policy_version),
            ).fetchone()
        return _to_document(row), True
    except Exception:
        if final_path is not None and final_path.exists():
            final_path.unlink()
            try:
                final_path.parent.rmdir()
            except OSError:
                pass
        raise


def get_document(conn, *, actor_id: UUID, case_id: UUID,
                 document_id: UUID, version: int | None = None) -> tuple[Document, str] | None:
    row = conn.execute(
        """SELECT d.* FROM documents d JOIN cases c ON c.case_id = d.case_id
           JOIN actor_subject_access a ON a.subject_id = c.subject_id
             AND a.actor_id = %s AND a.can_read_case = true
           JOIN consent_purposes p ON p.consent_id = c.consent_id
             AND p.purpose = 'case_guidance' AND p.status = 'active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE d.case_id = %s AND d.document_id = %s
             AND (%s::integer IS NULL OR d.document_version = %s)""",
        (actor_id, case_id, document_id, version, version),
    ).fetchone()
    return (_to_document(row), row["storage_ref"]) if row else None


def create_analysis_run(conn, *, actor_id: UUID, case_id: UUID,
                        document_versions: list[DocumentVersionRef],
                        pipeline_version: str, force_new: bool, conversation_id=None, turn_id=None) -> tuple[AnalysisRun, bool]:
    with conn.transaction():
        allowed = conn.execute(
            """SELECT 1 FROM cases c JOIN actor_subject_access a
               ON a.subject_id = c.subject_id AND a.actor_id = %s
                 AND a.can_read_case = true
               JOIN consent_purposes p ON p.consent_id = c.consent_id
                 AND p.purpose = 'case_guidance' AND p.status = 'active'
                 AND (p.expires_at IS NULL OR p.expires_at > now())
               WHERE c.case_id = %s FOR SHARE OF c, a, p""",
            (actor_id, case_id),
        ).fetchone()
        if not allowed:
            raise AccessDenied()
        snapshot = []
        seen = set()
        for reference in document_versions:
            key = (reference.document_id, reference.document_version)
            if key in seen:
                raise ValueError("duplicate document version")
            seen.add(key)
            row = conn.execute(
                """SELECT document_id, document_version, source_hash
                   FROM documents WHERE case_id = %s AND document_id = %s
                     AND document_version = %s""",
                (case_id, reference.document_id, reference.document_version),
            ).fetchone()
            if row is None:
                raise AccessDenied()
            snapshot.append({
                "document_id": str(row["document_id"]),
                "document_version": row["document_version"],
                "source_hash": row["source_hash"],
            })
        snapshot.sort(key=lambda item: (item["document_id"], item["document_version"]))
        context=capture_context(conn,case_id,actor_id,conversation_id,turn_id)
        context_sources(conn,{'case_id':case_id,'context_snapshot':context},lock=True)
        input_hash = run_input_hash(snapshot,pipeline_version,context)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"run:{case_id}:{input_hash}",),
        )
        if not force_new:
            old = conn.execute(
                """SELECT * FROM analysis_runs WHERE case_id = %s AND input_hash = %s
                   AND status NOT IN ('failed', 'cancelled')
                   ORDER BY created_at DESC LIMIT 1""",
                (case_id, input_hash),
            ).fetchone()
            if old:
                return _to_run(old), False
        run_id = uuid4()
        row = conn.execute(
            """INSERT INTO analysis_runs
               (run_id, case_id, input_hash, schema_version, pipeline_version,
                document_versions, status, current_stage, execution_mode, context_snapshot)
               VALUES (%s, %s, %s, '0.1.0', %s, %s::jsonb, 'queued', 'parse', 'live',%s::jsonb)
               RETURNING *""",
            (run_id, case_id, input_hash, pipeline_version, json.dumps(snapshot),json.dumps(context)),
        ).fetchone()
        return _to_run(row), True


def run_input_hash(documents,pipeline_version,context=None):
    payload={'documents':documents,'pipeline_version':pipeline_version}
    if context is not None:
        payload['context_snapshot']=context
    return request_digest(payload)


def get_analysis_run(conn, *, actor_id: UUID, run_id: UUID) -> AnalysisRun | None:
    row = conn.execute(
        """SELECT r.* FROM analysis_runs r JOIN cases c ON c.case_id = r.case_id
           JOIN actor_subject_access a ON a.subject_id = c.subject_id
             AND a.actor_id = %s AND a.can_read_case = true
           JOIN consent_purposes p ON p.consent_id = c.consent_id
             AND p.purpose = 'case_guidance' AND p.status = 'active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE r.run_id = %s""",
        (actor_id, run_id),
    ).fetchone()
    return _to_run(row) if row else None


def get_evidence(conn, *, actor_id: UUID, evidence_id: UUID) -> Evidence | None:
    row = conn.execute(
        """SELECT e.* FROM evidence e JOIN cases c ON c.case_id = e.case_id
           JOIN actor_subject_access a ON a.subject_id = c.subject_id
             AND a.actor_id = %s AND a.can_read_case = true
           JOIN consent_purposes p ON p.consent_id = c.consent_id
             AND p.purpose = 'case_guidance' AND p.status = 'active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE e.evidence_id = %s""",
        (actor_id, evidence_id),
    ).fetchone()
    if row is None:
        return None
    span = None
    if row["text_start"] is not None:
        span = TextSpan(start=row["text_start"], end=row["text_end"],
                        text=row["text_value"], offset_unit=row["offset_unit"])
    bbox = tuple(row["bbox"]) if row["bbox"] is not None else None
    return Evidence(
        evidence_id=row["evidence_id"], case_id=row["case_id"],
        document_id=row["document_id"], document_version=row["document_version"],
        page_index=row["page_index"], text_span=span, bbox=bbox,
        extraction_method=row["extraction_method"], source_hash=row["source_hash"],
        parser_version=row["parser_version"],
    )


def get_facts(conn, *, actor_id: UUID, case_id: UUID, run_id: UUID) -> list[ExtractedFact] | None:
    allowed = conn.execute(
        """SELECT 1 FROM analysis_runs r JOIN cases c ON c.case_id=r.case_id
           JOIN actor_subject_access a ON a.subject_id=c.subject_id
             AND a.actor_id=%s AND a.can_read_case=true
           JOIN consent_purposes p ON p.consent_id=c.consent_id
             AND p.purpose='case_guidance' AND p.status='active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE c.case_id=%s AND r.run_id=%s""",
        (actor_id, case_id, run_id),
    ).fetchone()
    if not allowed:
        return None
    rows = conn.execute(
        "SELECT * FROM extracted_facts WHERE case_id=%s AND run_id=%s ORDER BY fact_type",
        (case_id, run_id),
    ).fetchall()
    return [ExtractedFact(
        field_id=row["fact_id"], fact_type=row["fact_type"], run_id=row["run_id"],
        case_id=row["case_id"], value=row["value"], raw_value=row["raw_value"],
        status=row["status"], assertion=row["assertion"], evidence_ids=row["evidence_ids"],
        confidence_score=row["confidence_score"], confidence_method=row["confidence_method"],
        unit=row["unit"], derivation=row["derivation"], alternatives=row["alternatives"],
        missing_reason=row["missing_reason"], extractor_version=row["extractor_version"],
    ) for row in rows]


def get_events(conn, *, actor_id: UUID, case_id: UUID, run_id: UUID) -> EventBundle | None:
    allowed = conn.execute(
        """SELECT 1 FROM analysis_runs r JOIN cases c ON c.case_id=r.case_id
           JOIN actor_subject_access a ON a.subject_id=c.subject_id
             AND a.actor_id=%s AND a.can_read_case=true
           JOIN consent_purposes p ON p.consent_id=c.consent_id
             AND p.purpose='case_guidance' AND p.status='active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE c.case_id=%s AND r.run_id=%s""",
        (actor_id, case_id, run_id),
    ).fetchone()
    if not allowed:
        return None
    event_rows = conn.execute(
        "SELECT * FROM medical_events WHERE case_id=%s AND run_id=%s ORDER BY event_type",
        (case_id, run_id),
    ).fetchall()
    relation_rows = conn.execute(
        "SELECT * FROM event_relations WHERE case_id=%s AND run_id=%s ORDER BY relation_type,from_event_id",
        (case_id, run_id),
    ).fetchall()
    builder_version = event_rows[0]["builder_version"] if event_rows else "medical-event-builder-v1"
    events = [MedicalEvent(
        event_id=row["event_id"], case_id=row["case_id"], encounter_id=row["encounter_id"],
        event_type=row["event_type"], assertion=row["assertion"], occurred_at=row["occurred_at"],
        time_precision=row["time_precision"], attributes=row["attributes"],
        evidence_ids=row["evidence_ids"], confidence_score=row["confidence_score"],
        related_event_ids=[],
    ) for row in event_rows]
    relations = [EventRelation(
        from_event_id=row["from_event_id"], relation_type=row["relation_type"],
        to_ref=row["to_ref"], evidence_ids=row["evidence_ids"], status=row["status"],
    ) for row in relation_rows]
    return EventBundle(case_id=case_id, run_id=run_id, events=events,
                       relations=relations, builder_version=builder_version)


def get_insights(conn, *, actor_id: UUID, case_id: UUID, run_id: UUID) -> list[Insight] | None:
    allowed = conn.execute(
        """SELECT ac.role FROM analysis_runs r JOIN cases c ON c.case_id=r.case_id
           JOIN actors ac ON ac.actor_id=%s AND ac.active=true
           JOIN actor_subject_access a ON a.subject_id=c.subject_id
             AND a.actor_id=ac.actor_id AND a.can_read_case=true
           JOIN consent_purposes p ON p.consent_id=c.consent_id
             AND p.purpose='case_guidance' AND p.status='active'
             AND (p.expires_at IS NULL OR p.expires_at > now())
           WHERE c.case_id=%s AND r.run_id=%s""", (actor_id, case_id, run_id),
    ).fetchone()
    if not allowed:
        return None
    patient_filter = " AND review_status IN ('approved','corrected')" if allowed["role"] == "patient" else ""
    rows = conn.execute(
        "SELECT * FROM insights WHERE case_id=%s AND run_id=%s" + patient_filter +
        " ORDER BY category,label,created_at", (case_id, run_id),
    ).fetchall()
    return [Insight(
        insight_id=r["insight_id"], case_id=r["case_id"], run_id=r["run_id"],
        category=r["category"], label=r["label"], severity=r["severity"],
        confidence=r["confidence"], confidence_method=r["confidence_method"],
        evidence_ids=r["evidence_ids"], rationale=r["rationale"],
        uncertainty=r["uncertainty"], suggested_action=r["suggested_action"],
        review_required=r["review_required"], review_status=r["review_status"],
        judgment_status=r["judgment_status"], rule_version=r["rule_version"],
        knowledge_refs=r["knowledge_refs"],
    ) for r in rows]


def get_report(conn, *, actor_id: UUID, case_id: UUID, version: int, patient_view: bool = False) -> Report | None:
    row = conn.execute(
        """SELECT r.*,ac.role FROM reports r JOIN cases c ON c.case_id=r.case_id
           JOIN actors ac ON ac.actor_id=%s AND ac.active=true
           JOIN actor_subject_access a ON a.subject_id=c.subject_id
             AND a.actor_id=ac.actor_id AND a.can_read_case=true
           JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
           JOIN consent_purposes p ON p.consent_id=c.consent_id
             AND p.purpose='case_guidance' AND p.status='active'
             AND (p.expires_at IS NULL OR p.expires_at>now())
           WHERE r.case_id=%s AND r.report_version=%s""", (actor_id, case_id, version),
    ).fetchone()
    if not row:
        return None
    if row['role']=='medical_reviewer' and not patient_view:
        try:
            run=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE run_id=%s AND case_id=%s',
                             (row['run_id'],row['case_id'])).fetchone()
            if not run:
                return None
            context_sources(conn,run)
        except ValueError:
            return None
    if (patient_view or row['role']!='medical_reviewer') and not patient_report_visible(conn,row):
        return None
    return _to_report(row)


def patient_report_visible(conn, row) -> bool:
    if row['status'] not in {'published','superseded'} or row['policy_version']!=POLICY_VERSION:
        return False
    allowed = conn.execute("""SELECT 1 FROM report_releases rel JOIN cases c ON c.case_id=rel.case_id
        JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
        JOIN consent_purposes p ON p.consent_id=co.consent_id AND p.purpose='case_guidance'
          AND p.status='active' AND (p.expires_at IS NULL OR p.expires_at>clock_timestamp())
        WHERE rel.report_id=%s AND rel.case_id=%s AND rel.consent_id=co.consent_id
          AND rel.consent_version=co.version""",(row['report_id'],row['case_id'])).fetchone()
    if not allowed or row['memory_refs']:
        return False
    if any(c['review_status'] in {'pending','rejected'} for s in row['sections'] for c in s['claims']):
        return False
    try:
        run=conn.execute('SELECT case_id,context_snapshot FROM analysis_runs WHERE run_id=%s AND case_id=%s',
                         (row['run_id'],row['case_id'])).fetchone()
        if not run:
            return False
        context_sources(conn,run)
        material = '\n'.join(e['text_value'] or '' for e in conn.execute(
            'SELECT text_value FROM evidence WHERE case_id=%s AND run_id=%s',
            (row['case_id'],row['run_id'])).fetchall())
        check_report_knowledge(_to_report(row),material)
    except (ValueError,OSError):
        return False
    return True


def _to_report(row) -> Report:
    return Report(report_id=row["report_id"], case_id=row["case_id"], run_id=row["run_id"],
        report_version=row["report_version"], status=row["status"], sections=row["sections"],
        actions=row["actions"], input_hash=row["input_hash"], model_id=row["model_id"],
        prompt_version=row["prompt_version"], knowledge_version=row["knowledge_version"],
        policy_version=row["policy_version"], memory_refs=row["memory_refs"],
        consent_refs=row["consent_refs"], validation_errors=row["validation_errors"],
        created_at=row["created_at"])


def _to_case(row: dict) -> Case:
    external = None
    if row["source_system"] is not None:
        external = ExternalRef(source_system=row["source_system"], external_id=row["external_case_id"])
    return Case(case_id=row["case_id"], subject_id=row["subject_id"],
                external_case_ref=external, consent_refs=[row["consent_id"]],
                data_origin=row["data_origin"], user_context=row["user_context"],
                version=row["version"], created_at=row["created_at"])


def _to_document(row: dict) -> Document:
    return Document(
        document_id=row["document_id"], case_id=row["case_id"],
        document_version=row["document_version"], document_type=row["document_type"],
        media_type=row["media_type"], byte_size=row["byte_size"],
        page_count=row["page_count"], source_hash=row["source_hash"],
        source_ref=row["source_ref"], status=row["status"],
        policy_version=row["policy_version"], created_at=row["created_at"],
    )


def _to_run(row: dict) -> AnalysisRun:
    references = [
        {"document_id": item["document_id"], "document_version": item["document_version"]}
        for item in row["document_versions"]
    ]
    return AnalysisRun(
        run_id=row["run_id"], case_id=row["case_id"], input_hash=row["input_hash"],
        schema_version=row["schema_version"], pipeline_version=row["pipeline_version"],
        document_versions=references, status=row["status"],
        current_stage=row["current_stage"], stage_results=row["stage_results"],
        attempt=row["attempt"], max_attempts=row["max_attempts"], error=row["error"],
        execution_mode=ExecutionMode(row["execution_mode"]), started_at=row["started_at"],
        finished_at=row["finished_at"], created_at=row["created_at"],
    )
