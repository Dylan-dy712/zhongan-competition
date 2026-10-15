"""Database-backed page router and parser worker."""

import hashlib
import io
import json
import os
import re
import signal
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from uuid import uuid4

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader

from .repository import connect
from .fact_extractor import (ADMISSION_RE, DATE_TOKEN, DISCHARGE_RE, EXTRACTOR_VERSION,
                             UNATTRIBUTED, collect_encounter_dates, extract_facts,
                             merge_model_candidates, normalized_date)
from .event_builder import BUILDER_VERSION, build_events
from .cost_breakdown import cost_fact, has_cost_conflicts, report_cost_context
from .report_context import context_sources
from .insight_detector import RULE_VERSION, deterministic_candidates, infer_disease_code, merge_semantic_candidates
from .insight_llm import PROMPT_VERSION as INSIGHT_PROMPT_VERSION, SCHEMA_VERSION as INSIGHT_SCHEMA_VERSION, detect_semantic
from .knowledge_assembler import KnowledgeAssembler, PackExcludedError
from .report_builder import POLICY_VERSION as REPORT_POLICY_VERSION, map_report_sources, validate_and_complete
from .report_llm import PROMPT_VERSION as REPORT_PROMPT_VERSION, draft_report
from .contracts.core import Action
from .contracts.knowledge import DiseaseCode
from .llm_extractor import PROMPT_VERSION, SCHEMA_VERSION as MODEL_SCHEMA_VERSION, OpenAiCompatibleExtractor, validate_evidence_quotes
from .ocr import OCR_METHOD, OCR_VERSION, Ocr, create_ocr, page_ocr_method
from .document_quality import classify_material
from . import medical_records
from .parse_cache import cached_pages,save_page,require_parse_scope,payload_digest
from .volcengine_ocr import VolcengineOcr


TEXT_PARSER_VERSION = "controlled-text-v1"
PDF_PARSER_VERSION = "pypdf-6.6.2-v1"
ROUTING_VERSION = "page-router-v1"
stop_requested = False


def worker_error_code(exc: Exception) -> str:
    value = str(exc)
    if re.fullmatch(r'OCR_PROVIDER_ERROR:[A-Za-z0-9_.-]{1,80}', value):
        return value
    return value if value.isupper() else 'PARSE_FAILED'


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


def evidence_for_page(document,page):
    """Prepare once so report cost context and SQL evidence refer to the same source spans."""
    if not page['text']:
        return []
    if page_ocr_method(page):
        spans=[]
        cursor=0
        for block in page['blocks']:
            if block.get('metadata', {}).get('needs_clearer_photo'):
                continue
            value=block['text']
            spans.append((cursor,cursor+len(value),value,block.get('bbox')))
            cursor+=len(value)+1
    else:
        spans=[(*chunk,None) for chunk in text_chunks(page['text'])]
    return [{'evidence_id':uuid4(),'text':value,'document_id':document['document_id'],
             'document_version':document['document_version'],'page_index':page['page_index'],
             'start':start,'end':end,'bbox':bbox} for start,end,value,bbox in spans]


VISIT_RE = re.compile(r"(?:就诊|门诊|开单|开立|申请|检查)(?:时间|日期)\s*[:：]?\s*(" + DATE_TOKEN + r")")
STAY_MATCH_WINDOW_DAYS = 90


def assign_encounter_keys(parsed_documents) -> dict:
    """Group parsed pages into per-visit encounter keys.

    A page joins the admission stay whose date it carries (a discharge-only page may
    join a stay that started shortly before); visit-dated pages stay outpatient and
    everything else stays explicitly unattributed. Over-splitting is preferred over
    silently merging distinct visits.
    """
    markers = {}
    for document, pages in parsed_documents:
        for page in pages:
            text = page.get("text") or ""
            kind, iso = None, None
            admission, discharge, visit = (ADMISSION_RE.search(text), DISCHARGE_RE.search(text),
                                           VISIT_RE.search(text))
            if admission and (iso := normalized_date(admission.group(1))):
                kind = "inpatient"
            elif discharge and (iso := normalized_date(discharge.group(1))):
                kind = "discharge"
            elif visit and (iso := normalized_date(visit.group(1))):
                kind = "outpatient"
            markers[(document["document_id"], document["document_version"], page["page_index"])] = (kind, iso)
    admissions = {iso for kind, iso in markers.values() if kind == "inpatient"}
    keys = {}
    for identity, (kind, iso) in markers.items():
        if kind == "inpatient":
            keys[identity] = f"encounter:inpatient:{iso}"
        elif kind == "discharge":
            earlier = sorted((day for day in admissions if day <= iso), reverse=True)
            matched = bool(earlier) and (date.fromisoformat(iso) -
                                         date.fromisoformat(earlier[0])).days <= STAY_MATCH_WINDOW_DAYS
            keys[identity] = f"encounter:inpatient:{earlier[0]}" if matched else UNATTRIBUTED
        elif kind == "outpatient":
            keys[identity] = f"encounter:outpatient:{iso}"
        else:
            keys[identity] = UNATTRIBUTED
    return keys


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


def ocr_page(image_bytes: bytes, width: int, height: int, base: dict, ocr: Ocr):
    result = ocr.recognize(image_bytes, width, height)
    kind, certainty = classify_material(result['text'])
    uncertain = 0
    for block in result['blocks']:
        score = block.get('metadata', {}).get('confidence_score')
        if isinstance(score, (int, float)) and score < .8:
            block.setdefault('metadata', {})['needs_clearer_photo'] = True
            uncertain += 1
    # Preserve low-confidence OCR in page_blocks for auditing, but never feed it
    # to facts, amounts, clinical suggestions or the narrative as confirmed text.
    text = '\n'.join(block['text'] for block in result['blocks']
                     if not block.get('metadata', {}).get('needs_clearer_photo')) if uncertain else result['text']
    base.update({
        "text": text or None,
        "status": "parsed" if text else "unreadable",
        "requires_ocr": False,
        "parser_version": getattr(ocr, 'version', OCR_VERSION),
        "blocks": result["blocks"],
        "metadata": {
            **base["metadata"], "ocr_method": getattr(ocr, 'method', OCR_METHOD),
            "ocr_request_id": result["request_id"], "ocr_angle": result["angle"],
            "ocr_line_count": len(result["blocks"]),
            "photo_quality": {"material_type":kind,"type_certainty":certainty,
                              "uncertain_lines":uncertain,"readable_lines":len(result['blocks'])-uncertain,
                              "needs_reupload":bool(uncertain or not text),"method":"ocr-line-triage-v1"},
        },
    })
    return base


def parse_pdf(path: Path, ocr: Ocr | None = None, cached=None, checkpoint=None):
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise RuntimeError("PDF_ENCRYPTED")
    pages = []
    rendered_pdf = None
    for page_index, page in enumerate(reader.pages):
        if cached and page_index in cached:
            pages.append(cached[page_index]);continue
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
            ocr = ocr or create_ocr()
            rendered_pdf = rendered_pdf or pdfium.PdfDocument(str(path))
            bitmap = rendered_pdf[page_index].render(scale=2.0)
            image = bitmap.to_pil().convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92)
            parsed_page = ocr_page(output.getvalue(), image.width, image.height, parsed_page, ocr)
        pages.append(parsed_page)
        if checkpoint:checkpoint(parsed_page)
    return pages


def route_document(document: dict, path: Path, pipeline_version: str, ocr: Ocr | None = None, cached=None, checkpoint=None):
    def complete(pages):
        if checkpoint:
            for page in pages:checkpoint(page)
        return pages
    if pipeline_version == "text-parser-v1":
        if document["media_type"] != "text/plain":
            raise RuntimeError("PARSER_NOT_IMPLEMENTED")
        return [cached[0]] if cached and 0 in cached else complete(parse_controlled_text(document,path))
    if pipeline_version != "document-parser-v1":
        raise RuntimeError("PARSER_NOT_IMPLEMENTED")
    if document["media_type"] == "text/plain":
        return [cached[0]] if cached and 0 in cached else complete(parse_controlled_text(document,path))
    if document["media_type"] == "application/pdf":
        return parse_pdf(path,ocr,cached,checkpoint)
    if document["media_type"] in {"image/jpeg", "image/png"}:
        if cached and 0 in cached:return [cached[0]]
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
        return complete([ocr_page(path.read_bytes(),width,height,page,ocr or create_ocr())])
    raise RuntimeError("PARSER_NOT_IMPLEMENTED")


def analyze_models(material, knowledge_entries, user_context, source_refs, fact_inputs,
                   encounter_dates, advance, knowledge_excluded=False):
    """Overlap independent network calls; SQL and release checks stay on the caller."""
    started = time.monotonic()
    timings = {}
    def measured(name, call, *args, **kwargs):
        before = time.monotonic()
        try:
            return call(*args, **kwargs)
        finally:
            timings[name] = round(time.monotonic()-before, 3)

    fields = {"status":"not_configured","raw_output":None,"repaired_output":None,
              "candidates":{"candidates":[]},"personnel":[],"usage_metadata":{},
              "error_code":"LLM_NOT_CONFIGURED"}
    insights = {"status":"not_configured","candidates":[],"raw_output":None,
                "usage_metadata":{},"error_code":"LLM_NOT_CONFIGURED"}
    report = {"status":"not_configured","draft":{"sections":[],"actions":[]},"raw_output":None,
              "repaired_output":None,"usage_metadata":{},"error_code":"LLM_NOT_CONFIGURED"}
    provider, model_id = os.environ.get("LLM_PROVIDER","openai_compatible"), os.environ.get("LLM_MODEL_ID","unconfigured")
    configured = bool(material and os.environ.get("LLM_API_KEY"))
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='analysis-model') as pool:
        fields_future = insights_future = None
        if configured:
            extractor = OpenAiCompatibleExtractor()
            provider, model_id = extractor.provider, extractor.model_id
            fields_future = pool.submit(measured, 'extract_seconds', extractor.extract, material)
        advance('insights')
        if configured and not knowledge_excluded:
            knowledge = [{"entry_id":e.entry_id,"title":e.title,"content":e.content[:500],
                          "anchoring":e.anchoring} for e in knowledge_entries[:80]]
            insights_future = pool.submit(measured, 'insight_seconds', detect_semantic, material, knowledge)
        if fields_future:
            fields = validate_evidence_quotes(fields_future.result(), material)
        if insights_future:
            insights = insights_future.result()
        advance('guidance')
        if configured and not knowledge_excluded:
            from .guidance_context import care_priorities, select_guidance_knowledge
            reviewable = select_guidance_knowledge(knowledge_entries,fields,material,user_context)
            from .web_knowledge import supplement_knowledge
            reviewable,web_search=supplement_knowledge(reviewable,fields,material)
            priorities = care_priorities(insights,material,[entry['entry_id'] for entry in reviewable])
            from .analysis_sources import pack_sources
            packed, aliases = pack_sources([{'evidence':fact_inputs}])
            report = measured('guidance_seconds', draft_report, material, reviewable, user_context,
                user_sources=source_refs, structured_costs=report_cost_context(fact_inputs,fields['candidates'].get('cost_lines',[])),
                personnel=fields.get('personnel',[]), normalized_dates=encounter_dates, analysis_sources=packed,
                care_priorities=priorities, structured_fields=fields.get('candidates',{}))
            report.setdefault('usage_metadata',{})['web_search']=web_search
            report['reference_knowledge']=reviewable
            shared = report['draft'].get('patient_analysis')
            if shared:
                shared['evidence_refs'] = [aliases.get(ref,ref) for ref in shared['evidence_refs']]
                for citation in shared.get('citations',[]):
                    citation['source_refs'] = [aliases.get(ref,ref) for ref in citation.get('source_refs',[])]
                from .inline_citations import canonical_analysis_citations
                try:
                    report['draft']['patient_analysis'] = canonical_analysis_citations(shared,aliases,
                        [entry['entry_id'] for entry in reviewable])
                except (ValueError,KeyError,TypeError):
                    # Optional chat prose is unusable; retain the structured
                    # report and regenerate prose against live authorized sources.
                    report['draft']['patient_analysis'] = None
    performance = {'model_schedule':'parallel','model_seconds':timings,
                   'model_wall_seconds':round(time.monotonic()-started,3)}
    return fields, insights, report, provider, model_id, performance


def process_run(conn, run: dict, storage_root: Path) -> None:
    run_started = time.monotonic()
    parsed_documents = []
    def advance(stage):
        # Production connection is autocommit, so polling can observe each milestone.
        row = conn.execute("UPDATE analysis_runs SET current_stage=%s, lease_expires_at=now()+interval '5 minutes' WHERE run_id=%s AND lease_token=%s AND status='running' RETURNING run_id",
                           (stage, run['run_id'], run['lease_token'])).fetchone()
        if not row:
            raise RuntimeError('ANALYSIS_LEASE_LOST')
    try:
        advance('parse')
        source_refs=context_sources(conn,run)
        provider=os.environ.get('ZHONGAN_OCR_PROVIDER','tencent').strip().lower()
        ocr_version=VolcengineOcr.version if provider=='volcengine' else OCR_VERSION
        accepted_versions={TEXT_PARSER_VERSION,PDF_PARSER_VERSION,ocr_version}
        fingerprint=payload_digest({'cache':'parsed-pages-v1','pipeline':run['pipeline_version'],
            'text':TEXT_PARSER_VERSION,'pdf':PDF_PARSER_VERSION,'router':ROUTING_VERSION,
            'ocr_provider':provider,'ocr_version':ocr_version})
        reused_pages=recognized_pages=0
        for reference in run["document_versions"]:
            document = conn.execute(
                """SELECT * FROM documents WHERE case_id=%s AND document_id=%s
                   AND document_version=%s""",
                (run["case_id"], reference["document_id"], reference["document_version"]),
            ).fetchone()
            if document is None:
                raise RuntimeError("DOCUMENT_VERSION_NOT_FOUND")
            if reference.get('source_hash',document['source_hash'])!=document['source_hash']:
                raise RuntimeError('SOURCE_HASH_MISMATCH')
            path = Path(document["storage_ref"]).resolve()
            path.relative_to(storage_root)
            raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if raw_hash != document["source_hash"]:
                raise RuntimeError("SOURCE_HASH_MISMATCH")
            with conn.transaction():
                require_parse_scope(conn,run)
                cached=cached_pages(conn,document,fingerprint,accepted_versions,ROUTING_VERSION,run['pipeline_version'])
            def checkpoint(page):
                # Commit each successful page before another OCR/model request.
                with conn.transaction():
                    require_parse_scope(conn,run)
                    context_sources(conn,run,lock=True)
                    save_page(conn,document,fingerprint,page)
            pages = route_document(document,path,run['pipeline_version'],cached=cached,checkpoint=checkpoint)
            reused_pages+=sum(page['page_index'] in cached for page in pages)
            recognized_pages+=sum(page['page_index'] not in cached for page in pages)
            parsed_documents.append((document, pages))

        row=conn.execute('''UPDATE analysis_runs SET stage_results=jsonb_set(stage_results,'{parse}',%s::jsonb,true)
            WHERE run_id=%s AND lease_token=%s AND status='running' RETURNING run_id''',
            (json.dumps({'status':'completed','reused_pages':reused_pages,'processed_pages':recognized_pages}),
             run['run_id'],run['lease_token'])).fetchone()
        if not row:raise RuntimeError('ANALYSIS_LEASE_LOST')
        advance('extract')
        material = "\n\n".join(
            page["text"] for _document, pages in parsed_documents for page in pages if page["text"]
        )
        prepared_by_page={(document['document_id'],document['document_version'],page['page_index']):evidence_for_page(document,page)
            for document,pages in parsed_documents for page in pages}
        fact_inputs=[row for rows in prepared_by_page.values() for row in rows]
        encounter_keys = assign_encounter_keys(parsed_documents)
        for row in fact_inputs:
            row["encounter_key"] = encounter_keys[(row["document_id"], row["document_version"],
                                                   row["page_index"])]
        encounter_dates = collect_encounter_dates(fact_inputs)
        knowledge_entries = []
        knowledge_version = None
        knowledge_excluded = False
        assembler = KnowledgeAssembler()
        knowledge_version = assembler.knowledge_version
        knowledge_entries = assembler.select(DiseaseCode.ty,patient_visible=False).allowed
        disease_code = infer_disease_code(material)
        if disease_code is not None:
            try:
                assembler.check_exclusions(disease_code, material)
                knowledge_entries += assembler.select(
                    disease_code, patient_visible=False,
                ).allowed
            except PackExcludedError:
                knowledge_excluded = True
        case_meta = conn.execute(
            """SELECT c.user_context,c.consent_id,co.version AS consent_version
               FROM cases c JOIN consents co ON co.consent_id=c.consent_id WHERE c.case_id=%s""",
            (run["case_id"],),
        ).fetchone()
        parse_seconds = time.monotonic()-run_started
        model_result, insight_model_result, report_model_result, model_provider, model_id, performance = analyze_models(
            material, knowledge_entries,
            run['context_snapshot']['case_user_context'] if run.get('context_snapshot') else
            (case_meta["user_context"] if case_meta else None),
            source_refs, fact_inputs, encounter_dates, advance, knowledge_excluded)
        performance['parse_prepare_seconds'] = round(parse_seconds,3)
        performance['recognition_cache']={'reused_pages':reused_pages,'processed_pages':recognized_pages}

        advance('validate')
        evidence_ids = [str(row['evidence_id']) for row in fact_inputs]
        routing = []
        waiting_review = any(
            page["requires_ocr"] or page["requires_vision"] or page["status"] == "unreadable"
            for _document, pages in parsed_documents for page in pages
        )
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                         (f"case-report:{run['case_id']}",))
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
            context_sources(conn,run,lock=True)
            conn.execute("DELETE FROM evidence WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM page_blocks WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM extracted_facts WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM event_relations WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM medical_events WHERE run_id=%s", (run["run_id"],))
            conn.execute("DELETE FROM review_tasks WHERE run_id=%s AND status='pending'", (run["run_id"],))
            conn.execute("DELETE FROM insights WHERE run_id=%s", (run["run_id"],))
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
                             page_ocr_method(page) or
                             ("pdf_text_layer" if document["media_type"] == "application/pdf" else "controlled_text"),
                             document["source_hash"], page["parser_version"]),
                        )
                    for row in prepared_by_page[(document['document_id'],document['document_version'],page['page_index'])]:
                        evidence_id,start,end,value,bbox=(row[key] for key in ('evidence_id','start','end','text','bbox'))
                        conn.execute(
                            """INSERT INTO evidence
                               (evidence_id, run_id, case_id, document_id, document_version,
                                page_index, text_start, text_end, text_value, bbox, extraction_method,
                                source_hash, parser_version)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                            (evidence_id, run["run_id"], run["case_id"], document["document_id"],
                             document["document_version"], page["page_index"], start, end, value,
                             json.dumps(bbox),
                             page_ocr_method(page) or
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
            facts = merge_model_candidates(
                facts, model_result["candidates"].get("candidates", []), fact_inputs
            )
            expense_fact=cost_fact(fact_inputs,model_result['candidates'].get('cost_lines',[]))
            facts.append(expense_fact)
            if expense_fact['value'] and has_cost_conflicts(expense_fact['value']):
                waiting_review=True
            rule_insights = deterministic_candidates(fact_inputs, knowledge_entries)
            insights = merge_semantic_candidates(
                rule_insights, insight_model_result["candidates"], fact_inputs,
                {e.entry_id for e in knowledge_entries},
            )
            if knowledge_excluded:
                waiting_review = True
            if any(item["review_required"] for item in insights):
                waiting_review = True
            for item in insights:
                conn.execute(
                    """INSERT INTO insights
                       (insight_id,run_id,case_id,category,label,severity,confidence,
                        confidence_method,evidence_ids,rationale,uncertainty,suggested_action,
                        review_required,review_status,judgment_status,rule_version,knowledge_refs)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (item["insight_id"], run["run_id"], run["case_id"], item["category"],
                     item["label"], item["severity"], item["confidence"],
                     item["confidence_method"], json.dumps(item["evidence_ids"]),
                     item["rationale"], item["uncertainty"], item["suggested_action"],
                     item["review_required"], item["review_status"], item["judgment_status"],
                     item["rule_version"], json.dumps(item["knowledge_refs"])),
                )
                if item["review_required"]:
                    conn.execute(
                        """INSERT INTO review_tasks
                           (review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
                           VALUES (%s,%s,%s,'insight',%s,1,'pending',%s)
                           ON CONFLICT (target_type,target_id,target_version) DO NOTHING""",
                        (uuid4(), run["case_id"], run["run_id"], item["insight_id"],
                         "clinical_or_indeterminate_insight_requires_review"),
                    )
            evidence_texts = {str(x["evidence_id"]): x["text"] for x in fact_inputs}
            mapped_draft = map_report_sources(report_model_result["draft"], evidence_texts, source_refs)
            sections, action_drafts, report_errors = validate_and_complete(
                mapped_draft, evidence_texts,
                {e.entry_id for e in knowledge_entries} | {d['entry_id'] for d in report_model_result.get('reference_knowledge',[])}, source_refs,
                structured_dates=encounter_dates,
            )
            report_id = uuid4()
            actions = []
            for item in action_drafts:
                try:
                    actions.append(Action(action_id=uuid4(), report_id=report_id,
                        source_refs=item["source_refs"], owner_role=item["owner_role"],
                        action_text=item["action_text"], due_at=item.get("due_at"),
                        due_source=item["due_source"], status="proposed", priority=item["priority"],
                        rationale=item["rationale"]).model_dump(mode="json"))
                except Exception:
                    report_errors.append("INVALID_ACTION")
            has_pending_claim = any(c.review_status == "pending" for s in sections for c in s.claims)
            report_status = "pending_review" if waiting_review or report_errors or has_pending_claim else "ready"
            consent_refs = [{"consent_id": str(case_meta["consent_id"]),
                             "version": case_meta["consent_version"], "purpose": "case_guidance"}]
            conn.execute("DELETE FROM reports WHERE run_id=%s", (run["run_id"],))
            # New material must create a new case-level report version, not collide with v1.
            conn.execute("SELECT case_id FROM cases WHERE case_id=%s FOR UPDATE", (run["case_id"],))
            report_version = conn.execute(
                "SELECT COALESCE(MAX(report_version),0)+1 AS next_version FROM reports WHERE case_id=%s",
                (run["case_id"],),
            ).fetchone()["next_version"]
            conn.execute(
                """INSERT INTO reports(report_id,case_id,run_id,report_version,status,sections,actions,
                   input_hash,model_id,prompt_version,knowledge_version,policy_version,memory_refs,
                   consent_refs,validation_errors) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,'[]',%s::jsonb,%s::jsonb)""",
                (report_id, run["case_id"], run["run_id"], report_version, report_status,
                 json.dumps([s.model_dump(mode="json") for s in sections], ensure_ascii=False),
                 json.dumps(actions, ensure_ascii=False), run["input_hash"], model_id,
                 REPORT_PROMPT_VERSION, knowledge_version or "knowledge:none", REPORT_POLICY_VERSION,
                 json.dumps(consent_refs), json.dumps(report_errors)),
            )
            if report_status == 'pending_review':
                conn.execute("""INSERT INTO review_tasks
                    (review_id,case_id,run_id,target_type,target_id,target_version,status,reason)
                    VALUES (%s,%s,%s,'report',%s,%s,'pending','report_requires_review')""",
                    (uuid4(), run['case_id'], run['run_id'], report_id, report_version))
            conn.execute("""UPDATE review_tasks SET status='cancelled'
                WHERE case_id=%s AND target_type='report' AND target_version<%s AND status='pending'""",
                (run['case_id'], report_version))
            for fact in facts:
                conn.execute(
                    """INSERT INTO extracted_facts
                       (fact_id, run_id, case_id, fact_type, value, raw_value, status,
                        assertion, evidence_ids, confidence_score, confidence_method, unit,
                        derivation, alternatives, missing_reason, extractor_version, encounter_key)
                       VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s,%s,%s,
                               %s::jsonb,%s::jsonb,%s,%s,%s)""",
                    (fact["fact_id"], run["run_id"], run["case_id"], fact["fact_type"],
                     json.dumps(fact["value"], ensure_ascii=False), fact["raw_value"],
                     fact["status"], fact["assertion"], json.dumps(fact["evidence_ids"]),
                     fact["confidence_score"], fact["confidence_method"], fact["unit"],
                     json.dumps(fact["derivation"]), json.dumps(fact["alternatives"]),
                     fact["missing_reason"], fact["extractor_version"],
                     fact.get("encounter_key")),
                )
            encounters, events, relations = build_events(run["run_id"], facts, encounter_dates)
            for event in events:
                conn.execute(
                    """INSERT INTO medical_events
                       (event_id,run_id,case_id,encounter_id,event_type,assertion,occurred_at,
                        time_precision,attributes,evidence_ids,confidence_score,builder_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                    (event["event_id"], run["run_id"], run["case_id"], event["encounter_id"],
                     event["event_type"], event["assertion"], json.dumps(event["occurred_at"]),
                     event["time_precision"], json.dumps(event["attributes"], ensure_ascii=False),
                     json.dumps(event["evidence_ids"]), event["confidence_score"], BUILDER_VERSION),
                )
            for relation in relations:
                conn.execute(
                    """INSERT INTO event_relations
                       (relation_id,run_id,case_id,from_event_id,relation_type,to_ref,
                        evidence_ids,status,builder_version)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
                    (relation["relation_id"], run["run_id"], run["case_id"],
                     relation["from_event_id"], relation["relation_type"],
                     json.dumps(relation["to_ref"]), json.dumps(relation["evidence_ids"]),
                     relation["status"], BUILDER_VERSION),
                )
            conn.execute(
                """INSERT INTO model_extractions
                   (extraction_id, run_id, case_id, provider, model_id, prompt_version,
                    schema_version, status, raw_output, repaired_output, candidates,
                    usage_metadata, error_code, personnel)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb)
                   ON CONFLICT (run_id, provider, model_id, prompt_version) DO UPDATE SET
                    status=excluded.status, raw_output=excluded.raw_output,
                    repaired_output=excluded.repaired_output, candidates=excluded.candidates,
                    usage_metadata=excluded.usage_metadata, error_code=excluded.error_code,
                    personnel=excluded.personnel""",
                (uuid4(), run["run_id"], run["case_id"], model_provider, model_id,
                 PROMPT_VERSION, MODEL_SCHEMA_VERSION, model_result["status"],
                 json.dumps(model_result.get("raw_output"), ensure_ascii=False),
                 json.dumps(model_result.get("repaired_output"), ensure_ascii=False),
                 json.dumps(model_result["candidates"].get("candidates", []), ensure_ascii=False),
                 json.dumps(model_result.get("usage_metadata", {})), model_result.get("error_code"),
                 # The name/role/quote bindings the report relied on stay auditable,
                 # while candidates keeps its historical list shape.
                 json.dumps(model_result.get("personnel", []), ensure_ascii=False)),
            )
            conn.execute(
                """INSERT INTO model_extractions
                   (extraction_id,run_id,case_id,provider,model_id,prompt_version,
                    schema_version,status,raw_output,repaired_output,candidates,usage_metadata,error_code)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,NULL,%s::jsonb,%s::jsonb,%s)
                   ON CONFLICT (run_id,provider,model_id,prompt_version) DO UPDATE SET
                    status=excluded.status,raw_output=excluded.raw_output,
                    candidates=excluded.candidates,usage_metadata=excluded.usage_metadata,
                    error_code=excluded.error_code""",
                (uuid4(), run["run_id"], run["case_id"], model_provider, model_id,
                 INSIGHT_PROMPT_VERSION, INSIGHT_SCHEMA_VERSION, insight_model_result["status"],
                 json.dumps(insight_model_result.get("raw_output"), ensure_ascii=False),
                 json.dumps(insight_model_result["candidates"], ensure_ascii=False),
                 json.dumps(insight_model_result.get("usage_metadata", {})),
                 insight_model_result.get("error_code")),
            )
            conn.execute(
                """INSERT INTO model_extractions
                   (extraction_id,run_id,case_id,provider,model_id,prompt_version,schema_version,
                    status,raw_output,repaired_output,candidates,usage_metadata,error_code)
                   VALUES (%s,%s,%s,%s,%s,%s,'0.1.0',%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)
                   ON CONFLICT (run_id,provider,model_id,prompt_version) DO UPDATE SET
                    status=excluded.status,raw_output=excluded.raw_output,repaired_output=excluded.repaired_output,
                    candidates=excluded.candidates,usage_metadata=excluded.usage_metadata,error_code=excluded.error_code""",
                (uuid4(), run["run_id"], run["case_id"], model_provider, model_id,
                 REPORT_PROMPT_VERSION, report_model_result["status"],
                 json.dumps(report_model_result.get("raw_output"), ensure_ascii=False),
                 json.dumps(report_model_result.get("repaired_output"), ensure_ascii=False),
                 json.dumps(report_model_result["draft"], ensure_ascii=False),
                 json.dumps(report_model_result.get("usage_metadata", {})),
                 report_model_result.get("error_code")),
            )
            performance['elapsed_seconds'] = round(time.monotonic()-run_started,3)
            result = {"performance":performance,"parse": {
                "status": "waiting_review" if waiting_review else "completed",
                "reused_pages":reused_pages,"processed_pages":recognized_pages,
                "routing_version": ROUTING_VERSION, "pages": routing,
                "document_count": len(parsed_documents), "evidence_ids": evidence_ids,
            }, "extract": {
                "status": "completed", "extractor_version": EXTRACTOR_VERSION,
                "fact_count": len(facts),
                "observed_count": sum(fact["status"] == "observed" for fact in facts),
                "model_status": model_result["status"], "model_id": model_id,
                "prompt_version": PROMPT_VERSION,
            }, "reconcile": {
                "status": "completed", "builder_version": BUILDER_VERSION,
                "encounter_ids": sorted({str(value) for value in encounters.values()}),
                "encounter_count": len(encounters), "event_count": len(events),
                "relation_count": len(relations),
                # Persisted so review and release paths re-check date claims against
                # the same normalized timeline the report was drafted with.
                "structured_dates": encounter_dates,
            }, "insights": {
                "status": "waiting_review" if any(i["review_required"] for i in insights) or knowledge_excluded else "completed",
                "rule_version": RULE_VERSION, "insight_count": len(insights),
                "model_status": insight_model_result["status"],
                "prompt_version": INSIGHT_PROMPT_VERSION,
                "knowledge_version": knowledge_version,
                "knowledge_excluded": knowledge_excluded,
            }, "guidance": {
                "status": report_status, "report_id": str(report_id),
                "report_version": report_version, "prompt_version": REPORT_PROMPT_VERSION,
                "policy_version": REPORT_POLICY_VERSION,
                "validation_errors": report_errors, "model_status": report_model_result['status'],
                "reading_quality": report_model_result.get('usage_metadata',{}).get('guidance_delivery'),
            }}
            result_status = 'failed' if report_model_result['status'] == 'failed' else ('waiting_review' if waiting_review else 'completed')
            conn.execute(
                """UPDATE analysis_runs SET status=%s, current_stage='validate', stage_results=%s::jsonb,
                   finished_at=now(), error=%s::jsonb,
                   lease_token=NULL, lease_expires_at=NULL
                   WHERE run_id=%s AND lease_token=%s""",
                (result_status, json.dumps(result),
                 json.dumps({'code': report_model_result.get('error_code', 'REPORT_MODEL_FAILED'),
                             'retryable': report_model_result.get('retryable', True)}) if result_status == 'failed' else None,
                 run["run_id"], run["lease_token"]),
            )
            if result_status in ('completed','waiting_review'):
                try:
                    with conn.transaction():medical_records.enqueue(conn,run['run_id'])
                except Exception:
                    logging.getLogger(__name__).warning('MEDICAL_RECORD_QUEUE_UNAVAILABLE')
    except Exception as exc:
        code = worker_error_code(exc)
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
    # Separate connection/thread: record organization never delays report delivery or OCR.
    threading.Thread(target=medical_records.worker_loop,args=(dsn,lambda:stop_requested),name='medical-records',daemon=True).start()
    from . import conversation_titles
    threading.Thread(target=conversation_titles.worker_loop,args=(dsn,lambda:stop_requested),name='conversation-titles',daemon=True).start()
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
