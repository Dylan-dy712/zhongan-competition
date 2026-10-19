"""Add native Paddle table structure to frozen Paddle OCR, without reading gold."""
import argparse
import copy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import time
import unicodedata


class TableCells(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells, self.occupied = [], set()
        self.row, self.column, self.current = -1, 0, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row += 1
            self.column = 0
        elif tag in {'td', 'th'}:
            if self.current is not None or self.row < 0:
                raise ValueError('Malformed table HTML')
            while (self.row, self.column) in self.occupied:
                self.column += 1
            attrs = dict(attrs)
            rows, columns = int(attrs.get('rowspan', 1)), int(attrs.get('colspan', 1))
            if not 1 <= rows <= 1000 or not 1 <= columns <= 100:
                raise ValueError('Invalid table span')
            self.current = {'row_start': self.row, 'row_end': self.row + rows,
                            'column_start': self.column, 'column_end': self.column + columns,
                            'text': ''}
            for r in range(self.row, self.row + rows):
                for c in range(self.column, self.column + columns):
                    if (r, c) in self.occupied:
                        raise ValueError('Overlapping HTML cells')
                    self.occupied.add((r, c))
            self.column += columns
        elif tag == 'br' and self.current is not None:
            self.current['text'] += '\n'

    def handle_data(self, text):
        if self.current is not None:
            self.current['text'] += text

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.current is not None:
            self.current['text'] = self.current['text'].strip()
            self.cells.append(self.current)
            self.current = None


def compact(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--model-root', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--output-manifest', required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output, out_manifest = Path(args.output_root).resolve(), Path(args.output_manifest).resolve()
    if any(p.is_relative_to(repo) for p in (output, out_manifest)):
        parser.error('Medical artifacts must remain outside Git')
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
    models = Path(args.model_root).resolve()
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    import numpy as np
    from PIL import Image
    from paddleocr import TableRecognitionPipelineV2

    options = {}
    for prefix, name in [('layout_detection', 'PP-DocLayout-L'),
                         ('table_classification', 'PP-LCNet_x1_0_table_cls'),
                         ('wired_table_structure_recognition', 'SLANeXt_wired'),
                         ('wireless_table_structure_recognition', 'SLANeXt_wireless'),
                         ('wired_table_cells_detection', 'RT-DETR-L_wired_table_cell_det'),
                         ('wireless_table_cells_detection', 'RT-DETR-L_wireless_table_cell_det')]:
        options[prefix + '_model_name'] = name
        options[prefix + '_model_dir'] = str(models / name)
    pipeline = TableRecognitionPipelineV2(**options, use_doc_orientation_classify=False,
        use_doc_unwarping=False, use_layout_detection=True, use_ocr_model=False,
        device='gpu:0', cpu_threads=4, enable_mkldnn=False)
    completed = []
    for index, row in enumerate(manifest['documents'], 1):
        destination = output / (row['document_id'] + '.json')
        if destination.exists():
            raise RuntimeError('Use a fresh output directory')
        cache = json.loads(Path(row['ocr']).read_text(encoding='utf-8-sig'))
        if cache.get('ocr_status') != 'ok':
            raise ValueError('Frozen OCR must have succeeded')
        started = time.monotonic()
        rotation = row.get('image_rotation_degrees', 0)
        if rotation not in (0, 180):
            raise ValueError('Experiment supports the frozen 0/180 degree orientations only')
        with Image.open(row['image']) as image:
            upright = image.rotate(rotation, expand=True).convert('RGB')
        width, height = upright.size
        array = np.asarray(upright)[:, :, ::-1].copy()
        lines = cache['lines']
        boxes = []
        for line in lines:
            x1, y1, x2, y2 = line['bbox']
            if rotation:
                x1, y1, x2, y2 = 1-x2, 1-y2, 1-x1, 1-y1
            boxes.append([x1*width, y1*height, x2*width, y2*height])
        polys = [[[x1,y1],[x2,y1],[x2,y2],[x1,y2]] for x1,y1,x2,y2 in boxes]
        ocr = {'rec_boxes': np.asarray(boxes, dtype=np.float32),
               'rec_polys': np.asarray(polys, dtype=np.float32),
               'rec_texts': [line['text'] for line in lines],
               'rec_scores': np.asarray([line['score'] for line in lines]),
               'doc_preprocessor_res': {'output_img': array}}
        tables, diagnostics = [], []
        try:
            result = pipeline.predict(array, overall_ocr_res=ocr,
                use_table_orientation_classify=False, use_ocr_results_with_table_cells=False)[0]
            raw_tables = []
            for table_index, raw in enumerate(result['table_res_list']):
                raw_boxes = np.asarray(raw['cell_box_list']).tolist()
                raw_tables.append({'html': raw['pred_html'], 'cell_boxes': raw_boxes})
                cells = TableCells()
                cells.feed(raw['pred_html'])
                if cells.current is not None or len(cells.cells) != len(raw_boxes):
                    diagnostics.append({'table': table_index, 'reason': 'html_cell_box_count_mismatch',
                                        'html_cells': len(cells.cells), 'boxes': len(raw_boxes)})
                    continue
                for i, (cell, box) in enumerate(zip(cells.cells, raw_boxes)):
                    if len(box) != 4 or not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height:
                        raise ValueError('Invalid native table cell geometry')
                    matched = [j for j,b in enumerate(boxes)
                               if box[0] <= (b[0]+b[2])/2 <= box[2]
                               and box[1] <= (b[1]+b[3])/2 <= box[3]]
                    matched.sort(key=lambda j: (boxes[j][1], boxes[j][0]))
                    literal = compact(''.join(lines[j]['text'] for j in matched)) == compact(cell['text'])
                    scores = [lines[j]['score'] for j in matched if isinstance(lines[j].get('score'), (int,float))]
                    confidence = min(scores)*100 if scores and len(scores)==len(matched) else None
                    normalized = [box[0]/width, box[1]/height, box[2]/width, box[3]/height]
                    if rotation:
                        normalized = [1-normalized[2], 1-normalized[3], 1-normalized[0], 1-normalized[1]]
                    cell.update(id=f't{table_index}c{i}', bbox=normalized, confidence=confidence,
                                source_ocr_lines=matched,
                                confidence_method='minimum_source_ocr_score_not_structure_confidence',
                                review_required=not literal or confidence is None)
                tables.append({'table_index': table_index, 'type': 1, 'cells': cells.cells,
                               'provider': 'paddle_table_recognition_v2'})
            write(output / (row['document_id'] + '.native.json'), {'tables': raw_tables})
            status = 'completed' if not diagnostics else 'partial'
        except Exception as exc:
            status = 'failed'
            diagnostics.append({'reason': type(exc).__name__, 'detail': str(exc)})
            tables = []
        combined = copy.deepcopy(cache)
        combined.update(tables=tables, table_structure_status=status,
            table_structure_diagnostics=diagnostics,
            table_structure_seconds=round(time.monotonic()-started, 3),
            original_ocr_parser_version=cache.get('parser_version'),
            parser_version='paddle-v5-gpu960-tablemagic-v1')
        # Explicit fallback retains original OCR; never label failed structure as success.
        write(destination, combined)
        updated = dict(row, ocr=str(destination),
                       ocr_sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
        completed.append(updated)
        write(out_manifest, dict(manifest, documents=completed))
        print({'page':index, 'total':len(manifest['documents']), 'status':status,
               'tables':len(tables), 'cells':sum(len(t['cells']) for t in tables),
               'seconds':combined['table_structure_seconds']}, flush=True)


if __name__ == '__main__':
    main()
