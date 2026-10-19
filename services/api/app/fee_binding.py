"""Verify table row identity against original OCR cells, without reference labels."""
from decimal import Decimal, InvalidOperation
import unicodedata


def compact(value):
    return ''.join(unicodedata.normalize('NFKC', str(value)).split())


def fee_columns(cells):
    names = {c['column_start'] for c in cells
             if compact(c['text']) in {'名称', '项目名称', '费用名称', '收费项目名称', '药品名称'}}
    amounts = {c['column_start'] for c in cells
               if compact(c['text']).split('(')[0] in {'金额', '总金额', '费用金额', '合计金额'}}
    return names, amounts


def direct_fee_rows(cells, start, end):
    """Only transcribe an unambiguous single name/total column pair; otherwise defer."""
    names, amounts = fee_columns(cells)
    if len(names) != 1 or len(amounts) != 1:
        return None
    name_column, amount_column = next(iter(names)), next(iter(amounts))
    headers = [c for c in cells if c['column_start'] == name_column
               and compact(c['text']) in {'名称', '项目名称', '费用名称', '收费项目名称', '药品名称'}]
    first_data_row = min(c['row_end'] for c in headers)
    candidates = [c for c in cells if c['column_start'] == name_column
                  and max(start, first_data_row) <= c['row_start'] < end and compact(c['text'])
                  and not compact(c['text']).startswith(('小计', '合计', '总计', '本页合计'))]
    rows = []
    for name in candidates:
        totals = [c for c in cells if c['column_start'] == amount_column
                  and c['row_start'] == name['row_start']]
        if len(totals) != 1:
            return None
        amount = totals[0]
        if any(c['row_end'] != c['row_start'] + 1 or c['column_end'] != c['column_start'] + 1
               or not isinstance(c.get('confidence'), (int, float)) or c['confidence'] < 90
               for c in (name, amount)):
            return None
        try:
            value = Decimal(compact(amount['text']).replace(',', '').removeprefix('¥').removesuffix('元'))
        except InvalidOperation:
            return None
        if not value.is_finite():
            return None
        rows.append({'detailName': name['text'], 'feeAmount': float(value),
                     'confidence': {'detailName': name['confidence'] / 100,
                                    'feeAmount': amount['confidence'] / 100},
                     'evidence_quote': name['text'] + ' | ' + amount['text'],
                     'source_cells': [name['id'], amount['id']]})
    return rows or None


def validate_fee_binding(item, cells, start, end, *, allow_visual_name=False):
    by_id = {cell['id']: cell for cell in cells}
    if not item.source_cells or not set(item.source_cells) <= by_id.keys():
        raise ValueError('fee row requires original cell references')
    name_columns, amount_columns = fee_columns(cells)
    referenced = [by_id[key] for key in dict.fromkeys(item.source_cells)]
    names = [c for c in referenced if c['column_start'] in name_columns
             and c['row_end'] == c['row_start'] + 1
             and (allow_visual_name or compact(c['text']) == compact(item.detailName))]
    amounts = [c for c in referenced if c['column_start'] in amount_columns]
    item.binding_status = 'visual_review_required'
    item.binding_reason = 'ambiguous_headers_or_nonliteral_name'
    if len(amount_columns) != 1 or len(names) != 1 or len(amounts) != 1:
        return
    name, amount = names[0], amounts[0]
    if not start <= name['row_start'] < end:
        raise ValueError('fee name is outside the requested source row range')
    if amount['row_end'] != amount['row_start'] + 1:
        item.binding_reason = 'merged_amount_cell'
        return
    if name['row_start'] != amount['row_start']:
        raise ValueError('fee name and total amount reference different source rows')
    raw = compact(amount['text']).replace(',', '').removeprefix('¥').removesuffix('元')
    try:
        observed = Decimal(raw)
    except InvalidOperation:
        item.binding_reason = 'unreadable_amount_cell'
        return
    if not observed.is_finite() or observed != Decimal(str(item.feeAmount)):
        raise ValueError('fee amount differs from the referenced total amount cell')
    item.binding_status = 'verified_cells'
    item.binding_reason = 'literal_name_and_total_amount_in_same_source_row'
    item.source_row = name['row_start']
    if compact(name['text']) != compact(item.detailName):
        item.binding_status = 'verified_amount_visual_name'
        item.binding_reason = 'amount_verified_in_cells_name_corrected_from_local_image'
        item.raw_ocr_name = name['text']
