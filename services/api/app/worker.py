"""Database-backed page router and parser worker."""

import hashlib
import io
import json
import os
import re
import signal
import time
from pathlib import Path
from uuid import uuid4

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader

from .repository import connect
from .fact_extractor import EXTRACTOR_VERSION, extract_facts
from .tencent_ocr import OCR_METHOD, OCR_VERSION, TencentOcr


TEXT_PARSER_VERSION = "controlled-text-v1"
PDF_PARSER_VERSION = "pypdf-6.6.2-v1"
ROUTING_VERSION = "page-router-v1"
stop_requested = False


def request_stop(*_args) -> None:
    global stop_requested
    stop_requested = True


def claim_run(conn):
    lease = uuid4()
    with conn.transaction():
        row = conn.execute(
            """SELECT * FROM analysis_runs
               WHERE status = 'queued' AND attempt < max_attempts
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        return conn.execute(
            """UPDATE analysis_runs SET status='running', attempt=attempt+1,
               lease_token=%s, lease_expires_at=now()+interval '5 minutes',
               started_at=coalesce(started_at, now()), error=NULL
               WHERE run_id=%s RETURNING *""",
            (lease, row["run_id"]),
        ).fetchone()


def text_chunks(text: str, limit: int = 2000):
    for start in range(0, len(text), limit):
        end = min(start + limit, len(text))
        if text[start:end].strip():
            yield start, end, text[start:end]


def page_image_count(page) -> int:
    try:
        resources = page.get("/Resources")
        if resources is None:
            return 0
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return 0
        return sum(
            1 for value in xobjects.get_object().values()
            if value.get_object().get("/Subtype") == "/Image"
        )
    except Exception:
        return 0


def page_source_hash(page, text: str) -> str:
    digest = hashlib.sha256()
    try:
        contents = page.get_contents()
        if contents is not None:
            digest.update(contents.get_data())
    except Exception:
        pass
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def looks_like_title(line: str) -> bool:
    compact = line.strip()
    if not compact or len(compact) > 80:
        return False
    return bool(re.match(r"^(第[一二三四五六七八九十百0-9]+[章节]|[0-9]+(?:\.[0-9]+)*[、. ]|[一二三四五六七八九十]+、)", compact))


def text_blocks(text: str, image_count: int = 0):
    blocks = []
    order = 0
    for paragraph in re.split(r"\n\s*\n", text):
        value = paragraph.strip()
        if not value:
            continue
        first_line = value.splitlines()[0]
        block_type = "title" if looks_like_title(first_line) and len(value.splitlines()) == 1 else "paragraph"
        blocks.append({"type": block_type, "order": order, "text": value,
                       "metadata": {"structure_source": "text_heuristic"}})
        order += 1
    for image_index in range(image_count):
        blocks.append({"type": "image", "order": order, "text": None,
                       "metadata": {"image_index": image_index, "analysis_status": "vision_required"}})
        order += 1
    return blocks


def parse_controlled_text(document: dict, path: Path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("DOCUMENT_UNREADABLE") from None
    return [{
        "page_index": 0, "page_kind": "native_text", "text": text,
        "content_hash": hashlib.sha256(raw).hexdigest(), "status": "parsed",
        "requires_ocr": False, "requires_vision": False,
        "parser_version": TEXT_PARSER_VERSION,
        "blocks": text_blocks(text), "metadata": {"media_type": "text/plain"},
    }]


def ocr_page(image_bytes: bytes, width: int, height: int, base: dict, ocr: TencentOcr):
    result = ocr.recognize(image_bytes, width, height)
    text = result["text"]
    base.update({
        "text": text or None,
        "status": "parsed" if text else "unreadable",
        "requires_ocr": False,
        "parser_version": OCR_VERSION,
        "blocks": result["blocks"],
        "metadata": {
            **base["metadata"], "ocr_method": OCR_METHOD,
            "ocr_request_id": result["request_id"], "ocr_angle": result["angle"],
            "ocr_line_count": len(result["blocks"]),
        },
    })
    return base


def parse_pdf(path: Path, ocr: TencentOcr | None = None):
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError("PDF_ENCRYPTED")
    pages = []
    rendered_pdf = None
    for page_index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        image_count = page_image_count(page)
        text_count = len(text.strip())
        if text_count >= 40 and image_count == 0:
            kind, requires_ocr, requires_vision, status = "native_text", False, False, "parsed"
        elif text_count >= 40:
            kind, requires_ocr, requires_vision, status = "mixed", False, True, "parsed"
        elif image_count:
            kind, requires_ocr, requires_vision, status = "scanned", True, False, "unreadable"
        else:
            kind, requires_ocr, requires_vision, status = "unreadable", False, False, "unreadable"
        parsed_page = {
            "page_index": page_index, "page_kind": kind, "text": text or None,
            "content_hash": page_source_hash(page, text), "status": status,
            "requires_ocr": requires_ocr, "requires_vision": requires_vision,
            "parser_version": PDF_PARSER_VERSION,
            "blocks": text_blocks(text, image_count),
            "metadata": {"media_type": "application/pdf", "image_count": image_count,
                         "extracted_code_points": len(text)},
        }
        if requires_ocr:
            ocr = ocr or TencentOcr()
            rendered_pdf = rendered_pdf or pdfium.PdfDocument(str(path))
            bitmap = rendered_pdf[page_index].render(scale=2.0)
            image = bitmap.to_pil().convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92)
            parsed_page = ocr_page(output.getvalue(), image.width, image.height, parsed_page, ocr)
        pages.append(parsed_page)
    return pages


def route_document(document: dict, path: Path, pipeline_version: str, ocr: TencentOcr | None = None):
    if pipeline_version == "text-parser-v1":
        if document["media_type"] != "text/plain":
            raise RuntimeError("PARSER_NOT_IMPLEMENTED")
        return parse_controlled_text(document, path)
    if pipeline_version != "document-parser-v1":
        raise RuntimeError("PARSER_NOT_IMPLEMENTED")
    if document["media_type"] == "text/plain":
        return parse_controlled_text(document, path)
    if document["media_type"] == "application/pdf":
        return parse_pdf(path, ocr)
    if document["media_type"] in {"image/jpeg", "image/png"}:
        with Image.open(path) as image:
            width, height = image.size
        page = {
            "page_index": 0, "page_kind": "scanned", "text": None,
            "content_hash": document["source_hash"], "status": "unreadable",
            "requires_ocr": True, "requires_vision": False,
            "parser_version": ROUTING_VERSION,
            "blocks": [{"type": "image", "order": 0, "text": None,
                        "metadata": {"analysis_status": "ocr_required"}}],
            "metadata": {"media_type": document["media_type"], "image_count": 1},
        }
        return [ocr_page(path.read_bytes(), width, height, page, ocr or TencentOcr())]
    raise RuntimeError("PARSER_NOT_IMPLEMENTED")


def process_run(conn, run: dict, storage_root: Path) -> None:
    parsed_documents = []
    try:
        for reference in run["document_versions"]:
            document = conn.execute(
                """SELECT * FROM documents WHERE case_id=%s AND document_id=%s
                   AND document_version=%s""",
                (run["case_id"], reference["document_id"], reference["document_version"]),
            ).fetchone()
            if document is None:
                raise RuntimeError("DOCUMENT_VERSION_NOT_FOUND")
            path = Path(document["storage_ref"]).resolve()
            path.relative_to(storage_root)
            raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if raw_hash != document["source_hash"]:
                raise RuntimeError("SOURCE_HASH_MISMATCH")
            pages = route_document(document, path, run["pipeline_version"])
            parsed_documents.append((document, pages))

        evidence_ids = []
        fact_inputs = []
        routing = []
        waiting_review = any(
            page["requires_ocr"] or page["requires_vision"] or page["status"] == "unreadable"
            for _document, pages in parsed_documents for page in pages
        )
        with conn.transaction():
            authorized = conn.execute(
                """SELECT 1 FROM analysis_runs r JOIN cases c ON c.case_id=r.case_id
                   JOIN consent_purposes p ON p.consent_id=c.consent_id
                     AND p.purpose='case_guidance' AND p.status='active'
                     AND (p.expires_at IS NULL OR p.expires_at > now())
                   WHERE r.run_id=%s AND r.lease_token=%s AND r.status='running'
                   FOR SHARE OF r, c, p""",
                (run["run_id"], run["lease_token"]),
            ).fetchone()
            if not authorized:
                conn.execute(
                    """UPDATE analysis_runs SET status='cancelled', finished_at=now(),
                       lease_token=NULL, lease_expires_at=NULL,
                       error=%s::jsonb WHERE run_id=%s AND lease_token=%s""",
                    (json.dumps({"code": "AUTHORIZATION_REVOKED", "retryable": False}),
                     run["run_id"], run["lease_token"]),
                )
                return
            conn.execute("DELETE FROM evidence WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM page_blocks WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM extracted_facts WHERE run_id=%s", (run["run_id"],))
            for document, pages in parsed_documents:
                for page in pages:
                    routing.append({
                        "document_id": str(document["document_id"]),
                        "page_index": page["page_index"], "page_kind": page["page_kind"],
                        "requires_ocr": page["requires_ocr"],
                        "requires_vision": page["requires_vision"],
                    })
                    conn.execute(
                        """INSERT INTO document_pages
                           (document_id, document_version, page_index, text_content,
                            content_hash, parser_version, status, page_kind, routing_version,
                            requires_ocr, requires_vision, structure_metadata)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                           ON CONFLICT (document_id, document_version, page_index)
                           DO UPDATE SET text_content=excluded.text_content,
                             content_hash=excluded.content_hash, parser_version=excluded.parser_version,
                             status=excluded.status, page_kind=excluded.page_kind,
                             routing_version=excluded.routing_version,
                             requires_ocr=excluded.requires_ocr,
                             requires_vision=excluded.requires_vision,
                             structure_metadata=excluded.structure_metadata""",
                        (document["document_id"], document["document_version"], page["page_index"],
                         page["text"], page["content_hash"], page["parser_version"], page["status"],
                         page["page_kind"], ROUTING_VERSION, page["requires_ocr"],
                         page["requires_vision"], json.dumps(page["metadata"])),
                    )
                    for block in page["blocks"]:
                        conn.execute(
                            """INSERT INTO page_blocks
                               (block_id, run_id, case_id, document_id, document_version,
                                page_index, block_type, reading_order, text_content, bbox, metadata,
                                extraction_method, source_hash, parser_version)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)""",
                            (uuid4(), run["run_id"], run["case_id"], document["document_id"],
                             document["document_version"], page["page_index"], block["type"],
                             block["order"], block["text"], json.dumps(block.get("bbox")),
                             json.dumps(block["metadata"]),
                             OCR_METHOD if page["parser_version"] == OCR_VERSION else
                             ("pdf_text_layer" if document["media_type"] == "application/pdf" else "controlled_text"),
                             document["source_hash"], page["parser_version"]),
                        )
                    if page["text"]:
                        if page["parser_version"] == OCR_VERSION:
                            spans = []
                            cursor = 0
                            for block in page["blocks"]:
                                value = block["text"]
                                spans.append((cursor, cursor + len(value), value, block.get("bbox")))
                                cursor += len(value) + 1
                        else:
                            spans = [(*chunk, None) for chunk in text_chunks(page["text"])]
                        for start, end, value, bbox in spans:
                            evidence_id = uuid4()
                            evidence_ids.append(str(evidence_id))
                            fact_inputs.append({"evidence_id": evidence_id, "text": value})
                            conn.execute(
                                """INSERT INTO evidence
                                   (evidence_id, run_id, case_id, document_id, document_version,
                                    page_index, text_start, text_end, text_value, bbox, extraction_method,
                                    source_hash, parser_version)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                                (evidence_id, run["run_id"], run["case_id"], document["document_id"],
                                 document["document_version"], page["page_index"], start, end, value,
                                 json.dumps(bbox),
                                 OCR_METHOD if page["parser_version"] == OCR_VERSION else
                                 ("pdf_text_layer" if document["media_type"] == "application/pdf" else "controlled_text"),
                                 document["source_hash"], page["parser_version"]),
                            )
                document_status = "parsing" if any(
                    page["requires_ocr"] or page["requires_vision"] or page["status"] == "unreadable"
                    for page in pages
                ) else "parsed"
                conn.execute(
                    "UPDATE documents SET status=%s, page_count=%s WHERE document_id=%s",
                    (document_status, len(pages), document["document_id"]),
                )
            facts = extract_facts(fact_inputs)
            for fact in facts:
                conn.execute(
                    """INSERT INTO extracted_facts
                       (fact_id, run_id, case_id, fact_type, value, raw_value, status,
                        assertion, evidence_ids, confidence_score, confidence_method, unit,
                        derivation, alternatives, missing_reason, extractor_version)
                       VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s,%s,%s,
                               %s::jsonb,%s::jsonb,%s,%s)""",
                    (fact["fact_id"], run["run_id"], run["case_id"], fact["fact_type"],
                     json.dumps(fact["value"], ensure_ascii=False), fact["raw_value"],
                     fact["status"], fact["assertion"], json.dumps(fact["evidence_ids"]),
                     fact["confidence_score"], fact["confidence_method"], fact["unit"],
                     json.dumps(fact["derivation"]), json.dumps(fact["alternatives"]),
                     fact["missing_reason"], fact["extractor_version"]),
                )
            result = {"parse": {
                "status": "waiting_review" if waiting_review else "completed",
                "routing_version": ROUTING_VERSION, "pages": routing,
                "document_count": len(parsed_documents), "evidence_ids": evidence_ids,
            }, "extract": {
                "status": "completed", "extractor_version": EXTRACTOR_VERSION,
                "fact_count": len(facts),
                "observed_count": sum(fact["status"] == "observed" for fact in facts),
            }}
            conn.execute(
                """UPDATE analysis_runs SET status=%s, current_stage='validate', stage_results=%s::jsonb,
                   finished_at=CASE WHEN %s='completed' THEN now() ELSE NULL END,
                   lease_token=NULL, lease_expires_at=NULL
                   WHERE run_id=%s AND lease_token=%s""",
                ("waiting_review" if waiting_review else "completed", json.dumps(result),
                 "waiting_review" if waiting_review else "completed",
                 run["run_id"], run["lease_token"]),
            )
    except Exception as exc:
        code = str(exc) if str(exc).isupper() else "PARSE_FAILED"
        with conn.transaction():
            conn.execute(
                """UPDATE analysis_runs SET status='failed', finished_at=now(),
                   lease_token=NULL, lease_expires_at=NULL,
                   error=%s::jsonb WHERE run_id=%s AND lease_token=%s""",
                (json.dumps({"code": code, "retryable": False}),
                 run["run_id"], run["lease_token"]),
            )


def main() -> None:
    dsn = os.environ["ZHONGAN_DATABASE_URL"]
    storage_root = Path(os.environ["ZHONGAN_STORAGE_ROOT"]).resolve()
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop_requested:
        try:
            with connect(dsn) as conn:
                conn.autocommit = True
                run = claim_run(conn)
                if run is not None:
                    process_run(conn, run, storage_root)
                    continue
        except Exception:
            time.sleep(2)
        time.sleep(1)


if __name__ == "__main__":
    main()
