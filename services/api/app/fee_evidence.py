"""Bind fee evidence per row; a bad row must not erase independently supported rows."""
from decimal import Decimal, InvalidOperation
import re
from types import SimpleNamespace
from .fee_binding import compact, validate_fee_binding


def bind_fee_evidence(blocks, text, has_image, tables=None):
    audit = {'accepted_rows': 0, 'rejected_rows': [], 'visual_only_rows': 0}
    output, used_lines, used_cells = [], set(), set()
    source_lines = text.splitlines()
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
                        validate_fee_binding(candidate, table['cells'], 0,
                                             max(c['row_end'] for c in table['cells']))
                        if candidate.binding_status == 'verified_cells':
                            name_refs = {c['id'] for c in table['cells'] if c['id'] in refs
                                         and compact(c['text']) == compact(row['detailName'])}
                            if name_refs & used_cells:
                                failure = 'duplicate_source_name_cell'
                            else:
                                used_cells.update(name_refs)
                                verification = 'literal_source_cells_same_row'
                                quote = ' | '.join(c['text'] for c in table['cells'] if c['id'] in refs)
                                row.update(binding_status=candidate.binding_status,
                                           binding_reason=candidate.binding_reason, source_row=candidate.source_row)
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
                    'detailName': row['detailName'], 'reason': failure or 'no_same_row_source_support'})
                continue
            if quote:
                row['evidence_quote'] = quote
            row['evidence_verification'] = verification
            kept.append(row)
            audit['accepted_rows'] += 1
        if kept:
            output.append({**block, 'costDetailList': kept})
    return output, audit
