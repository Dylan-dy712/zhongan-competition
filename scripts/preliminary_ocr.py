"""Fresh OCR of manifest images; retain image hashes and safe progress only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from PIL import Image
from services.api.app.tencent_ocr import TencentOcr, OCR_VERSION
from scripts.preliminary_kr1 import load, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    output = Path(args.output_root)
    if output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('OCR medical data must stay outside the repository')
    os.environ.update({k:str(v) for k,v in load(args.config).items() if k.startswith('TENCENTCLOUD_')})
    rows = load(args.manifest)['documents']
    if args.limit:
        rows = rows[:args.limit]
    def recognize(row):
        image = Path(row['image'])
        destination = output / row['case_id'] / (image.stem + '.json')
        if destination.exists():
            previous = load(destination)
            if previous.get('source_image_sha256') != row['image_sha256']:
                raise ValueError('cached OCR does not belong to source image')
            if previous['ocr_status'] == 'ok':
                return 'ok'
        try:
            if sha(image) != row['image_sha256']:
                raise ValueError('image changed after manifest freeze')
            with Image.open(image) as opened:
                width, height = opened.size
            result = TencentOcr().recognize(image.read_bytes(), width, height)
            cache = {'source_ref':f'{row["case_id"]}/{image.name}',
                     'source_image_sha256':row['image_sha256'], 'image_size':[width,height],
                     'parser':'tencent_general_accurate', 'parser_version':OCR_VERSION,
                     'text':result['text'], 'request_id':result['request_id'],
                     'ocr_status':'ok' if result['text'].strip() else 'empty',
                     'lines':[{'text':block['text'], 'bbox':block['bbox'],
                               'score':block['metadata']['confidence_score']} for block in result['blocks']]}
        except Exception as exc:
            cache = {'source_image_sha256':row['image_sha256'], 'ocr_status':'failed',
                     'error_code':type(exc).__name__, 'text':'', 'lines':[]}
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
