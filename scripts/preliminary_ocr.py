"""Fresh OCR of manifest images; retain image hashes and safe progress only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from PIL import Image
from services.api.app.tencent_ocr import TencentOcr, OCR_VERSION, TABLE_OCR_VERSION
from scripts.preliminary_kr1 import load, write
from services.api.app.ocr import recognize_routed, create_ocr, provider_ocr_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--config')
    parser.add_argument('--provider', choices=['tencent', 'paddle'], default='tencent')
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--table', action='store_true', help='use Tencent table recognition V3')
    parser.add_argument('--auto-table', action='store_true', help='classify general OCR, then request tables only for fee/settlement pages')
    parser.add_argument('--table-new-model', action='store_true', help='use V3 optional complex-table model')
    args = parser.parse_args()
    if args.table and args.auto_table:
        parser.error('choose --table or --auto-table')
    if args.table_new_model and not (args.table or args.auto_table):
        parser.error('--table-new-model requires --table or --auto-table')
    if args.provider == 'paddle' and (args.table or args.auto_table or args.table_new_model):
        parser.error('Paddle text provider has no table structure module; do not mix Tencent table calls')
    if args.config:
        os.environ.update({k:str(v) for k,v in load(args.config).items()
                           if k.startswith(('TENCENTCLOUD_', 'ZHONGAN_PADDLE_'))})
    parser_version = (TABLE_OCR_VERSION + ('-new-model' if args.table_new_model else '')
                      if args.table else OCR_VERSION)
    if args.auto_table:
        parser_version += '-auto-table-v1' + ('-new-model' if args.table_new_model else '')
    if args.provider == 'paddle':
        parser_version = provider_ocr_version('paddle')
    output = Path(args.output_root)
    if output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('OCR medical data must stay outside the repository')
    rows = load(args.manifest)['documents']
    if args.limit:
        rows = rows[:args.limit]
    def recognize(row):
        image = Path(row['image'])
        destination = output / row['case_id'] / (image.stem + '.json')
        if destination.exists():
            previous = load(destination)
            if previous.get('material_layout') != row.get('material_layout'):
                raise ValueError('material layout changed; use a new OCR output directory')
            if (previous['ocr_status'] == 'ok' and previous.get('parser_version') == parser_version
                    and previous.get('image_rotation_degrees', 0) == (row.get('image_rotation_degrees', 0) if args.provider == 'paddle' else 0)
                    and previous.get('table_routing', {}).get('status') != 'unavailable'):
                return 'ok'
        try:
            with Image.open(image) as opened:
                width, height = opened.size
            client = create_ocr(args.provider)
            if args.provider == 'paddle':
                result = client.recognize(image.read_bytes(), width, height,
                                          rotation_degrees=row.get('image_rotation_degrees', 0))
            else:
                result = (client.recognize_table(image.read_bytes(), width, height, use_new_model=args.table_new_model)
                          if args.table else recognize_routed(client, image.read_bytes(), width, height,
                              enable_table=args.auto_table, use_new_model=args.table_new_model))
            cache = {'source_ref':f'{row["case_id"]}/{image.name}',
                     'source_image_sha256':row['image_sha256'], 'image_size':[width,height],
                     'parser':client.method if args.provider == 'paddle' else 'tencent_table_accurate_v3' if args.table else 'tencent_general_accurate',
                     'parser_version':parser_version,
                     'text':result['text'], 'request_id':result['request_id'],
                     'ocr_angle':result['angle'],
                     'ocr_status':'ok' if result['text'].strip() else 'empty',
                     'image_rotation_degrees':row.get('image_rotation_degrees', 0) if args.provider == 'paddle' else 0,
                     'seconds':result.get('seconds'),
                     'lines':[{'text':block['text'], 'bbox':block['bbox'],
                               'score':block['metadata']['confidence_score']} for block in result['blocks']]}
            if 'tables' in result:
                cache['tables'] = result['tables']
            if args.auto_table:
                cache['material_routing'] = result['material_routing']
                cache['table_routing'] = result['table_routing']
        except Exception as exc:
            cache = {'source_image_sha256':row['image_sha256'], 'ocr_status':'failed',
                     'error_code':type(exc).__name__, 'text':'', 'lines':[]}
            if str(exc) in {'PADDLE_OCR_NATIVE_TIMEOUT', 'PADDLE_OCR_SERVICE_UNAVAILABLE'}:
                cache['provider_error'] = str(exc)
        if row.get('material_layout'):
            cache['material_layout'] = row['material_layout']
        write(destination, cache)
        return cache['ocr_status']
    counts = {}
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
        for future in as_completed([pool.submit(recognize,row) for row in rows]):
            status = future.result()
            counts[status] = counts.get(status,0)+1
            print({'done':sum(counts.values()),'total':len(rows),**counts},flush=True)


if __name__=='__main__':
    main()
