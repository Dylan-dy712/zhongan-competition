"""Connect evidence-bearing C page extraction to the existing case pipeline."""
import json
import os
from decimal import Decimal

from .document_fields import extract_document, DocumentExtractionFailure, PROMPT_VERSION, SCHEMA_VERSION
from .fact_extractor import assertion_for
from .llm_extractor import OpenAiCompatibleExtractor, ModelCandidate
from .material_layout import MaterialLayout, analyze_material_layout

VERSION = 'product-document-c-v1'


def enabled():
    return os.getenv('ZHONGAN_DOCUMENT_EXTRACTION', '') == 'C'


def provider():
    return OpenAiCompatibleExtractor(config_prefix='ZHONGAN_DOCUMENT_LLM_')


def layout(image_bytes):
    try:
        payload, content = analyze_material_layout(provider(), image_bytes)
        plan = MaterialLayout.model_validate_json(content).model_dump(mode='json')
        rotation = plan['rotation_degrees'] if plan['rotation_degrees'] is not None and plan['orientation_confidence'] >= .9 else 0
        return {'status': 'completed', 'plan': plan, 'adopted_rotation_degrees': rotation,
                'usage': payload.get('usage', {}), 'confidence_method': 'model_self_report_uncalibrated'}
    except Exception as exc:
        return {'status': 'failed', 'error_code': type(exc).__name__, 'adopted_rotation_degrees': 0}


def extract_page(page, image_bytes, plan):
    lines = [{'text': b['text'], 'bbox': b.get('bbox'), 'score': b.get('metadata', {}).get('confidence_score')}
             for b in page['blocks'] if b.get('text')]
    text = '\n'.join(b['text'] for b in page['blocks'] if b.get('text'))
    try:
        prediction = extract_document(provider(), text, image_bytes,
            image_rotation_degrees=plan.get('adopted_rotation_degrees', 0),
            table_context=page['metadata'].get('tables'), ocr_lines=lines,
            material_layout=plan, experiment='C')
        status = 'partial' if prediction.get('fee_extraction', {}).get('status') == 'partial' else 'completed'
    except DocumentExtractionFailure as exc:
        prediction = {'fields': {}, 'confidence': {}, 'evidence': {}, 'failed_stage': exc.stage,
                      'error_code': exc.error_code, 'requires_review': True}
        status = 'failed'
    page['metadata']['document_extraction'] = {'version': VERSION, 'status': status,
        'model_id': provider().model_id, 'provider': provider().provider,
        'prompt_version': PROMPT_VERSION, 'schema_version': SCHEMA_VERSION,
        'prediction': {k: v for k, v in prediction.items() if k != 'raw_response'}}
    # A model transcription remains a separately marked, unreviewed source.
    # Never represent it as native OCR or silently overwrite the OCR text.
    quotes = [(key, quote, prediction.get('image_boxes', {}).get(key))
              for key, quote in prediction.get('evidence', {}).items() if quote]
    quotes += [('fee_row', row.get('evidence_quote'), None)
               for block in prediction.get('fields', {}).get('blocks', [])
               for row in block.get('costDetailList', []) if row.get('evidence_quote')]
    seen = set()
    for field, quote, box in quotes:
        if quote in seen or quote in text:
            continue
        seen.add(quote)
        page['blocks'].append({'type': 'paragraph', 'order': len(page['blocks']), 'text': quote,
            'bbox': box or [0, 0, 1, 1], 'metadata': {'structure_source': VERSION,
                'field': field, 'visual_transcription': True, 'independent_review_required': True,
                'coordinate_precision': 'field' if box else 'page'}})
    page['text'] = '\n'.join(b['text'] for b in page['blocks']
        if b.get('text') and not b.get('metadata', {}).get('needs_clearer_photo')) or None
    page['requires_vision'] = True  # retain the medical review gate for visual claims
    return page


def case_extraction(parsed_documents):
    candidates, documents = [], []
    for document, pages in parsed_documents:
        for page in pages:
            record = page['metadata'].get('document_extraction')
            if not record:
                continue
            prediction = record['prediction']
            documents.append({'document_id': str(document['document_id']),
                'document_version': document['document_version'], 'page_index': page['page_index'], **record})
            fields = prediction.get('fields', {})
            # The raw complete C result stays in documents, including fees and alternatives.
            for field, kind in [('diagnosis', 'diagnosis'), ('admissionDiagnosis', 'diagnosis'),
                                ('dischargeDiagnosis', 'diagnosis'), ('surgery', 'surgery'),
                                ('medication', 'medication'), ('inpatientDays', 'stay_days')]:
                value, quote = fields.get(field), prediction.get('evidence', {}).get(field, '')
                if value is None or not quote or prediction.get('field_status', {}).get(field) == 'derived':
                    continue
                for item in value if isinstance(value, list) else [value]:
                    raw = str(item)
                    if raw not in ''.join(quote.split()) and ''.join(raw.split()) not in ''.join(quote.split()):
                        continue
                    try:
                        candidate = ModelCandidate(fact_type=kind, raw_value=raw,
                            normalized_value=item, assertion=assertion_for(quote), evidence_quote=quote,
                            confidence_score=prediction.get('confidence', {}).get(field))
                        candidates.append(candidate.model_dump(mode='json', exclude_none=True))
                    except ValueError:
                        continue  # full source field is retained above, not truncated into a new fact
    if not documents:
        return None
    failed = sum(d['status'] == 'failed' for d in documents)
    return {'status': 'partial' if failed else 'completed', 'raw_output': None,
            'repaired_output': None, 'candidates': {'candidates': candidates, 'cost_lines': []},
            'personnel': [], 'usage_metadata': {'extraction_pipeline': VERSION, 'strategy': 'C',
                'document_extractions': documents, 'failed_pages': failed}, 'error_code': None,
            'structured_documents': documents}
