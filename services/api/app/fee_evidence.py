"""Bind fee evidence per row; a bad row must not erase independently supported rows."""
from decimal import Decimal, InvalidOperation
import re
from types import SimpleNamespace
from .fee_binding import compact, validate_fee_binding


def bind_fee_evidence(blocks, text, has_image, tables=None):
    audit = {'accepted_rows': 0, 'rejected_rows': [], 'visual_only_rows': 0}
    output, used_lines, used_cells = [], set(), set()
    source_lines = text.splitlines()
    billing_code_context = any(label in compact(text) for label in ('医保编码', '收费项目编码', '收费项目代码'))
    billing_suffix = re.compile(r'\s*[\[【（(]\s*(\d{12,}(?:-\d{5,})?)\s*[\]】）)]\s*$')
    for block_index, block in enumerate(blocks):
        kept = []
        for index, original in enumerate(block.get('costDetailList', [])):
            row = dict(original)
            verification, quote, failure = None, None, None
            refs = set(row.get('source_cells', []))
            if refs and tables:
                table = next((t for t in tables if refs <= {c['id'] for c in t.get('cells', [])}), None)
                if table is None:
                    failure = 'unknown_or_cross_table_source_cells'
                else:
                    candidate = SimpleNamespace(detailName=row['detailName'], feeAmount=row['feeAmount'],
                                                source_cells=list(refs))
                    try:
                        box = row.get('visual_source_box')
                        visual_name = bool(has_image and row.get('visual_correction_method') == 'local_name_crop_v1'
                            and isinstance(box, list) and len(box) == 4
                            and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box)
                            and box[0] < box[2] and box[1] < box[3])
                        validate_fee_binding(candidate, table['cells'], 0,
                                             max(c['row_end'] for c in table['cells']), allow_visual_name=visual_name)
                        if candidate.binding_status in {'verified_cells', 'verified_amount_visual_name'}:
                            name_refs = {c['id'] for c in table['cells'] if c['id'] in refs
                                         and compact(c['text']) == compact(getattr(candidate, 'raw_ocr_name', row['detailName']))}
                            if name_refs & used_cells:
                                failure = 'duplicate_source_name_cell'
                            else:
                                used_cells.update(name_refs)
                                verification = 'literal_source_cells_same_row'
                                if candidate.binding_status == 'verified_amount_visual_name':
                                    verification = 'local_visual_name_with_verified_amount_cell'
                                    row['raw_ocr_name'] = candidate.raw_ocr_name
                                quote = ' | '.join(c['text'] for c in table['cells'] if c['id'] in refs)
                                row.update(binding_status=candidate.binding_status,
                                           binding_reason=candidate.binding_reason, source_row=candidate.source_row)
                                # Preserve explicit billing categories separately from inferred semantics.
                                category_columns = {c['column_start'] for c in table['cells']
                                    if compact(c['text']) in {'费用类别', '收费类别', '费用分类', '收费分类', '项目类别'}}
                                source_categories = [c for c in table['cells']
                                    if c['column_start'] in category_columns
                                    and c['row_start'] == candidate.source_row
                                    and c['row_end'] == candidate.source_row + 1 and c['text'].strip()]
                                row.pop('sourceCategoryName', None)
                                row.pop('sourceCategoryCells', None)
                                if len(source_categories) == 1:
                                    row['sourceCategoryName'] = source_categories[0]['text']
                                    row['sourceCategoryCells'] = [source_categories[0]['id']]
                    except ValueError:
                        failure = 'invalid_source_row_binding'
            if verification is None and failure is None:
                for line_index, line in enumerate(source_lines):
                    if compact(row['detailName']) not in compact(line):
                        continue
                    values = []
                    for token in re.findall(r'(?<![\d.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![\d.])', line):
                        try:
                            values.append(Decimal(token.replace(',', '')))
                        except InvalidOperation:
                            continue
                    key = (line_index, compact(row['detailName']), str(row['feeAmount']))
                    if Decimal(str(row['feeAmount'])) in values and key not in used_lines:
                        used_lines.add(key)
                        verification = 'literal_ocr_row_requires_column_review'
                        quote = line
                        # Literal row support is weaker than a proven total-amount column.
                        row['binding_status'] = 'unverified'
                        break
            if verification is None and failure is None and has_image:
                verification = 'visual_transcription_requires_independent_review'
                row['binding_status'] = 'visual_review_required'
                audit['visual_only_rows'] += 1
            if verification is None:
                audit['rejected_rows'].append({'block_index': block_index, 'row_index': index,
                    'detailName': row['detailName'], 'candidate': original,
                    'reason': failure or 'no_same_row_source_support'})
                continue
            if quote:
                row['evidence_quote'] = quote
            # A separately labeled billing identifier can be printed inside the
            # name cell. Preserve its raw evidence, but keep it out of the name.
            # Short numbers, specifications and alphanumeric models stay intact.
            code = billing_suffix.search(row['detailName']) if billing_code_context else None
            if code and code.group(1) in compact(text) and row['detailName'][:code.start()].strip():
                row.update(raw_detail_name=row['detailName'],
                           normalized_detail_name=row['detailName'][:code.start()].rstrip(),
                           source_billing_codes=[code.group(1)],
                           name_normalization_method='separate_labeled_billing_identifier_v1')
                verification += '_billing_identifier_separated'
                audit['separated_billing_code_rows'] = audit.get('separated_billing_code_rows', 0) + 1
            row['evidence_verification'] = verification
            kept.append(row)
            audit['accepted_rows'] += 1
        if kept:
            output.append({**block, 'costDetailList': kept})
    return output, audit
