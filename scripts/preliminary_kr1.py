"""Prepare input/reference mapping, independently infer, and rescore KR1 documents.

Private outputs must stay outside the Git repository. Existing OCR caches are
explicitly labeled replay, not an end-to-end fresh OCR benchmark.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import unicodedata
import ast
from statistics import median
from pydantic import ValidationError

from services.api.app.document_fields import DIAGNOSES, NUMBERS, SCALARS, PROMPT_VERSION, extract_document, DocumentExtractionFailure
from services.api.app.llm_extractor import OpenAiCompatibleExtractor


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed_count(result):
    fields = (result or {}).get('fields', {})
    return (sum(value is not None and value != '' and value != [] for key,value in fields.items() if key != 'blocks')
            + sum(len(block.get('costDetailList', [])) for block in fields.get('blocks', [])))


def repair_name(value):
    try:
        return b''.join(b'\x80' if ch == '€' else ch.encode('gbk') for ch in value).decode('utf-8')
    except UnicodeError:
        return value


def mapping(gold_root, image_root, ocr_root):
    images = defaultdict(list)
    suffixes = defaultdict(list)
    for path in Path(image_root).rglob('*'):
        if path.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
            images[(path.parent.name, path.stem)].append(path)
            match = re.search(r'_\d+_\d+$', path.stem)
            if match:
                suffixes[(path.parent.name, match.group())].append(path)
    rows = []
    used = set()
    for gold in sorted(Path(gold_root).rglob('*.json')):
        identity = f'{gold.parent.name}/{gold.name}'
        candidates = images.get((gold.parent.name, gold.stem), [])
        method = 'exact_case_filename'
        if not candidates:
            candidates = images.get((gold.parent.name, repair_name(gold.stem)), [])
            method = 'reversible_filename_encoding'
        if not candidates:
            match = re.search(r'_\d+_\d+$', gold.stem)
            candidates = suffixes.get((gold.parent.name, match.group()), []) if match else []
            method = 'unique_case_page_timestamp'
        image = candidates[0] if len(candidates) == 1 else None
        if image is not None and str(image) in used:
            raise ValueError('a source image cannot be assigned to two reference documents')
        if image is not None:
            used.add(str(image))
        cache = Path(ocr_root) / gold.parent.name / (image.stem + '.json') if image else None
        rows.append({'document_id': hashlib.sha256(identity.encode()).hexdigest()[:24],
                     'case_id': gold.parent.name, 'reference': str(gold.resolve()),
                     'reference_sha256': sha(gold), 'image': str(image.resolve()) if image else None,
                     'image_sha256': sha(image) if image else None,
                     'mapping_method': method if image else 'unresolved',
                     'ocr': str(cache.resolve()) if cache and cache.exists() else None,
                     'ocr_sha256': sha(cache) if cache and cache.exists() else None})
    return {'version': 'preliminary-documents-v1', 'documents': rows,
            'summary': {'cases': len({r['case_id'] for r in rows}), 'documents': len(rows),
                        'mapped': sum(bool(r['image']) for r in rows),
                        'ocr_available': sum(bool(r['ocr']) for r in rows),
                        'mapping_methods': dict(Counter(r['mapping_method'] for r in rows))},
            'limits': ['70/30 purpose and official scoring are unconfirmed',
                       'OCR caches have no image hash provenance; original OCR is not rebenchmarked']}


def normalize(value):
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(Decimal(str(value)).normalize())
    # Typography only: keep clinical words, assertions, digits, units and entity boundaries.
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value)))
    return text


def normalize_number(value):
    """Compare typed numeric fields without changing identifier or entity strings."""
    if isinstance(value, bool):
        return normalize(value)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return normalize(value)
    return str(number.normalize()) if number.is_finite() else normalize(value)


def explicit_entities(value):
    """Normalize explicitly delimited reference lists, preserving brackets inside names.

    This is format conversion, not clinical entity inference from free prose.
    """
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return [value]
    text = unicodedata.normalize('NFKC', value).strip()
    if not (text.startswith('[') and text.endswith(']')):
        # A comma inside a clinical sentence is not an entity boundary.
        return [value]
    if text.startswith('[') and text.endswith(']'):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return parsed
        except (ValueError, SyntaxError):
            pass
        text = text[1:-1]
    result, chars, depth = [], [], 0
    for char in text:
        if char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        if char in ',;、' and depth == 0:
            if ''.join(chars).strip():
                result.append(''.join(chars).strip())
            chars = []
        else:
            chars.append(char)
    if ''.join(chars).strip():
        result.append(''.join(chars).strip())
    return result


def layout_text(cache):
    """Reconstruct OCR rows from boxes without using reference labels or values."""
    lines = cache.get('lines', [])
    if not lines or any(not isinstance(line.get('bbox'), list) or len(line['bbox']) != 4 for line in lines):
        return cache.get('text', '')
    rotation = cache.get('image_rotation_degrees', 0)
    if rotation not in (0, 90, 180, 270):
        raise ValueError('OCR layout rotation must be a cardinal angle')
    # Providers store evidence boxes in original-image coordinates. Read them in
    # the same upright orientation as the image sent to the extraction model.
    upright = []
    for line in lines:
        x1, y1, x2, y2 = line['bbox']
        box = {0: [x1, y1, x2, y2], 90: [y1, 1-x2, y2, 1-x1],
               180: [1-x2, 1-y2, 1-x1, 1-y1], 270: [1-y2, x1, 1-y1, x2]}[rotation]
        upright.append({**line, 'bbox': box})
    lines = upright
    names = [line for line in lines if normalize(line['text']) in
             {'名称', '项目名称', '费用名称', '收费名称', '药品名称'}]
    slopes = []
    if len(names) == 1:
        box = names[0]['bbox']
        nx, ny = (box[0]+box[2])/2, (box[1]+box[3])/2
        for line in lines:
            if normalize(line['text']) not in {'规格', '单位', '单价', '数量', '医保类别', '金额', '总金额', '费用金额'}:
                continue
            box = line['bbox']
            x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
            if x > nx+.08 and abs(y-ny) < .035:
                slopes.append((y-ny)/(x-nx))
    slope = median(slopes) if len(slopes) >= 2 else 0
    width, height = cache.get('image_size', [1, 1])
    if rotation in (90, 270):
        width, height = height, width
    if abs(math.degrees(math.atan2(slope*height, width))) > 8:
        slope = 0
    # Project onto the header baseline so a tilted amount stays with its name.
    # Preserve the original boxes and all text; this changes reading order only.
    def row_y(line):
        x1, y1, x2, y2 = line['bbox']
        return (y1+y2)/2-slope*(x1+x2)/2
    heights = [line['bbox'][3] - line['bbox'][1] for line in lines if line['bbox'][3] > line['bbox'][1]]
    tolerance = median(heights) * .45 if heights else .005
    rows = []
    for line in sorted(lines, key=row_y):
        y = row_y(line)
        if rows and abs(rows[-1][0] - y) <= tolerance:
            rows[-1][1].append(line)
        else:
            rows.append((y, [line]))
    return '\n'.join(' | '.join(line['text'] for line in sorted(items, key=lambda l: l['bbox'][0]))
                     for _, items in rows)


def atoms(fields, include_inferred_categories=False):
    result = defaultdict(Counter)
    for key in DIAGNOSES + SCALARS + NUMBERS:
        value = fields.get(key)
        if value is None or value == '' or value == []:
            continue
        values = explicit_entities(value) if key in DIAGNOSES + ('medication',) else value if isinstance(value, list) else [value]
        canonical = normalize_number if key in NUMBERS else normalize
        result[key].update(canonical(v) for v in values if v is not None and v != '')
    for block in fields.get('blocks', []):
        for line in block.get('costDetailList', []):
            if line.get('feeAmount') is None:
                continue
            # Do not mix inferred classification with directly recorded item identity/amount.
            result['cost_detail_name_amount'][(normalize(line.get('detailName', '')),
                                               normalize_number(line['feeAmount']))] += 1
            if line.get('itemCategoryName') and (include_inferred_categories or not line.get('category_inferred', False)):
                category_key = 'cost_semantic_category' if include_inferred_categories else 'cost_explicit_category'
                result[category_key][(normalize(line.get('detailName', '')),
                                                  normalize_number(line['feeAmount']),
                                                  normalize(line['itemCategoryName']))] += 1
    return result


def score(manifest, predictions_dir, include_inferred_categories=False):
    totals = defaultdict(Counter)
    errors = []
    failed = 0
    partial = 0
    in_progress = 0
    unannotated = 0
    for row in manifest['documents']:
        reference = load(row['reference'])
        if sha(row['reference']) != row['reference_sha256']:
            raise ValueError('reference changed after manifest was frozen')
        gold = atoms(reference['fields'], include_inferred_categories)
        unannotated += int(not reference['fields'])
        path = Path(predictions_dir) / (row['document_id'] + '.json')
        run = load(path) if path.exists() else {'status': 'missing'}
        if run.get('ocr_sha256') != row['ocr_sha256']:
            if run['status'] != 'missing':
                raise ValueError('prediction source does not match manifest')
        valid = run.get('status') in ('completed', 'partial')
        partial += int(run.get('status') == 'partial')
        in_progress += int(bool(run.get('in_progress')))
        if run.get('extraction_mode') == 'mock':
            raise ValueError('mock predictions are for plumbing only and cannot be scored as effect evidence')
        failed += int(not valid)
        predicted = atoms(run.get('result', {}).get('fields', {}), include_inferred_categories) if valid else {}
        # Missing reference keys are unannotated, not verified negatives.
        for key, expected in gold.items():
            actual = predicted.get(key, Counter())
            tp = sum((expected & actual).values())
            fp, fn = sum((actual - expected).values()), sum((expected - actual).values())
            missing = sum(expected.values()) if not actual else 0
            totals[key].update(tp=tp, fp=fp, fn=fn, expected=sum(expected.values()), missing=missing)
            if fp or fn:
                errors.append({'document_id': row['document_id'], 'field': key, 'fp': fp, 'fn': fn})
    def metrics(count):
        tp, fp, fn = count['tp'], count['fp'], count['fn']
        return {**dict(count), 'precision': tp / (tp + fp) if tp + fp else None,
                'recall': tp / (tp + fn) if tp + fn else None,
                'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
                'missing_rate': count['missing'] / count['expected'] if count['expected'] else None}
    combined = Counter()
    for count in totals.values():
        combined.update(count)
    return {'policy': ('document-fee-taxonomy-exact-v5' if include_inferred_categories
                       else 'document-explicit-list-opportunities-exact-v5'), 'official_metric_verified': False,
            'five_core_categories_fully_annotated': False,
            'limits': ['surgery/drug entities inside prose lack an independent normalized gold',
                       ('all annotated fee categories scored as semantic classification, not literal transcription'
                        if include_inferred_categories else
                        'absent reference fields are unannotated; inferred cost categories not scored'),
                       'replayed OCR is not fresh end-to-end OCR validation'],
            'documents': len(manifest['documents']), 'failed_or_missing_predictions': failed,
            'partially_completed_predictions': partial,
            'in_progress_predictions': in_progress,
            'prediction_acceptance_policy': 'observed-fields-in-completed-or-partial-v1',
            'empty_reference_documents': unannotated, 'overall': metrics(combined),
            'per_field': {key: metrics(c) for key, c in totals.items()}, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'infer', 'score'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--gold-root')
    parser.add_argument('--image-root')
    parser.add_argument('--ocr-root')
    parser.add_argument('--manifest')
    parser.add_argument('--predictions-dir')
    parser.add_argument('--config', help='private server configuration; never copied into outputs')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--ocr-layout', choices=['plain', 'bbox'], default='plain')
    parser.add_argument('--vision', action='store_true', help='read original image with OCR as optional context')
    parser.add_argument('--retry-partial', action='store_true', help='explicitly rerun partial documents under identical frozen settings')
    parser.add_argument('--disable-local-fee-review', action='store_true',
                        help='ablation: keep table OCR but disable selective image recovery')
    parser.add_argument('--include-inferred-categories', action='store_true',
                        help='score semantic fee classification too; changes policy to v3, not comparable to v2 totals')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    for output in (args.output, args.predictions_dir):
        if output and Path(output).resolve().is_relative_to(repo):
            parser.error('private outputs must remain outside the repository')
    if args.mode == 'prepare':
        if not all((args.gold_root, args.image_root, args.ocr_root)):
            parser.error('prepare requires gold, images and OCR roots')
        result = mapping(args.gold_root, args.image_root, args.ocr_root)
        write(args.output, result)
        print(json.dumps(result['summary']))
        return
    manifest = load(args.manifest)
    if args.limit:
        manifest = {**manifest, 'documents': manifest['documents'][:args.limit],
                    'evaluation_subset': f'fixed-first-{args.limit}-development-documents'}
    if args.mode == 'score':
        result = score(manifest, args.predictions_dir, args.include_inferred_categories)
        result['evaluation_subset'] = manifest.get('evaluation_subset', 'all-manifest-documents')
        write(args.output, result)
        print(json.dumps({k: result[k] for k in ('documents', 'failed_or_missing_predictions', 'overall')}))
        return
    if args.config:
        os.environ.update({k: str(v) for k, v in load(args.config).items() if k.startswith('LLM_')})
    os.environ['ZHONGAN_LOCAL_FEE_REVIEW'] = '0' if args.disable_local_fee_review else '1'
    provider = OpenAiCompatibleExtractor()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    implementation_hashes = {'runner': sha(__file__),
                             'extractor': sha(repo/'services/api/app/document_fields.py'),
                             'provider': sha(repo/'services/api/app/llm_extractor.py'),
                             'workload': sha(repo/'services/api/app/model_workloads.py'),
                             'routing': sha(repo/'services/api/app/material_routing.py'),
                             'fee_binding': sha(repo/'services/api/app/fee_binding.py'),
                             'fee_evidence': sha(repo/'services/api/app/fee_evidence.py')}
    rows = manifest['documents']
    def infer(row):
        destination = Path(args.predictions_dir) / (row['document_id'] + '.json')
        previous = {}
        if destination.exists():
            previous = load(destination)
            if previous.get('prompt_version') != PROMPT_VERSION or previous.get('model_id') != provider.model_id:
                raise ValueError('use a new predictions directory for a new model or prompt')
            if previous.get('implementation_sha256') != implementation_hashes:
                raise ValueError('runner changed; use a new predictions directory')
            if previous.get('ocr_sha256') != row.get('ocr_sha256'):
                raise ValueError('OCR source changed; use a new predictions directory')
            if previous.get('ocr_layout_method') != args.ocr_layout:
                raise ValueError('OCR layout changed; use a new predictions directory')
            if previous.get('vision') != args.vision:
                raise ValueError('vision mode changed; use a new predictions directory')
            if previous.get('local_fee_review_enabled', True) != (not args.disable_local_fee_review):
                raise ValueError('local fee review changed; use a new predictions directory')
            if previous.get('direct_fee_rows_enabled', False) != (os.environ.get('ZHONGAN_DIRECT_FEE_ROWS') == '1'):
                raise ValueError('direct fee experiment changed; use a new predictions directory')
            if previous.get('image_rotation_degrees', 0) != row.get('image_rotation_degrees', 0):
                raise ValueError('source image orientation changed; use a new predictions directory')
            if previous.get('extraction_mode') != ('mock' if provider.provider == 'mock' else 'live'):
                raise ValueError('execution mode changed; use a new predictions directory')
            if (previous.get('status') == 'completed' or
                previous.get('status') == 'partial' and not args.retry_partial) and not previous.get('in_progress'):
                return previous['status']
        run = {k: row[k] for k in ('document_id', 'image_sha256', 'ocr_sha256')}
        run.update(model_id=provider.model_id, prompt_version=PROMPT_VERSION, code_revision=revision,
                   extraction_mode='mock' if provider.provider == 'mock' else 'live', ocr_mode='replay', vision=args.vision,
                   implementation_sha256=implementation_hashes)
        run['image_rotation_degrees'] = row.get('image_rotation_degrees', 0)
        run['orientation_method'] = row.get('orientation_method', 'original_orientation')
        run['direct_fee_rows_enabled'] = os.environ.get('ZHONGAN_DIRECT_FEE_ROWS') == '1'
        run['local_fee_review_enabled'] = not args.disable_local_fee_review
        start = time.monotonic()
        if previous.get('status') == 'partial' and previous.get('result'):
            saved = max((previous['result'], previous.get('recovery_snapshot', {})), key=observed_count)
            run['result'] = saved
            # Persist alongside new checkpoints, so interruption cannot erase an older useful partial.
            run['recovery_snapshot'] = saved
        def checkpoint(result, stage):
            run.update(result=result, status='partial', in_progress=True,
                       last_completed_stage=stage, seconds=round(time.monotonic() - start, 3))
            write(destination, run)
            print(json.dumps({'document_id': row['document_id'], 'stage': stage, 'checkpoint': True,
                'fee_rows': sum(len(b.get('costDetailList', [])) for b in result['fields'].get('blocks', []))}), flush=True)
        try:
            if not row['ocr'] or sha(row['ocr']) != row['ocr_sha256']:
                raise ValueError('missing or changed OCR source')
            cache = load(row['ocr'])
            run['ocr_status'] = cache.get('ocr_status', 'not_recorded')
            if run['ocr_status'] in {'failed', 'empty'}:
                # Do not bypass a failed OCR provider with image-only LLM output in OCR comparisons.
                raise ValueError('OCR did not produce a usable recognition result')
            if not cache.get('text', '').strip() and not args.vision:
                raise ValueError('OCR source is empty')
            run['ocr_layout_method'] = args.ocr_layout
            image_bytes = None
            if args.vision:
                image_bytes = Path(row['image']).read_bytes()
            run['result'] = extract_document(provider, layout_text(cache) if args.ocr_layout == 'bbox' else cache['text'],
                image_bytes, image_rotation_degrees=row.get('image_rotation_degrees', 0),
                table_context=cache.get('tables'), on_progress=checkpoint, ocr_lines=cache.get('lines'))
            run['status'] = ('partial' if run['result'].get('fee_extraction', {}).get('status') == 'partial'
                             else 'completed')
        except Exception as exc:
            run.update(status='partial' if run.get('result') else 'failed', error_code=type(exc).__name__)
            if isinstance(exc, ValidationError):
                run['validation_errors'] = [{'type': e['type'], 'loc': e['loc']}
                                            for e in exc.errors(include_input=False, include_context=False)]
            if isinstance(exc, DocumentExtractionFailure):
                run.update(failed_stage=exc.stage, failed_response=exc.response,
                           validation_errors=exc.validation_errors, stage_error_code=exc.error_code,
                           failed_usage=exc.usage, finish_reason=exc.finish_reason, http_status=exc.http_status)
                run['provider_error'] = exc.provider_error
        if run['status'] != 'completed' and observed_count(run.get('recovery_snapshot')) > observed_count(run.get('result')):
            run['result'] = run['recovery_snapshot']
            run['status'] = 'partial'
            run['retained_previous_partial'] = True
        run.pop('recovery_snapshot', None)
        run['seconds'] = round(time.monotonic() - start, 3)
        run['in_progress'] = False
        write(destination, run)
        return run['status']
    counts = Counter()
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
        for future in as_completed([pool.submit(infer, row) for row in rows]):
            counts[future.result()] += 1
            if sum(counts.values()) % 10 == 0:
                print(json.dumps({'done': sum(counts.values()), 'total': len(rows), **dict(counts)}), flush=True)
    write(args.output, {'model_id': provider.model_id, 'prompt_version': PROMPT_VERSION,
                        'counts': dict(counts), 'manifest_sha256': sha(args.manifest)})
    print(json.dumps(dict(counts)), flush=True)


if __name__ == '__main__':
    main()
