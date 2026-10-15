"""One synthetic OCR request, without logging keys, images, or returned text."""
import argparse
import io
import json
import os
from pathlib import Path
import time

from PIL import Image, ImageDraw
from services.api.app.ocr import create_ocr

CONFIG_KEYS = {'ZHONGAN_OCR_PROVIDER', 'VOLCENGINE_OCR_ACCESS_KEY_ID',
               'VOLCENGINE_OCR_SECRET_ACCESS_KEY', 'VOLCENGINE_OCR_SECURITY_TOKEN'}


def load_config(path: Path):
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        if key.strip() in CONFIG_KEYS:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def synthetic_image():
    image = Image.new('RGB', (900, 600), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((60, 100), 'SYNTHETIC OCR TEST 2026', fill='black', font_size=36)
    draw.text((60, 180), 'TOTAL 123.00', fill='black', font_size=36)
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue(), image.width, image.height


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('.secrets/volcengine-ocr.env'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    load_config(args.config)
    started = time.monotonic()
    try:
        ocr = create_ocr('volcengine')
        result = ocr.recognize(*synthetic_image())
        verified = 'OCR' in result['text'].upper() and '123.00' in result['text']
        summary = {'status': 'passed' if verified else 'recognition_mismatch', 'provider': 'volcengine',
                   'method': ocr.method, 'request_id': result['request_id'], 'lines': len(result['blocks']),
                   'with_bbox': sum(block['bbox'] is not None for block in result['blocks']),
                   'with_confidence': sum(block['metadata']['confidence_score'] is not None for block in result['blocks']),
                   'synthetic_text_verified': verified}
    except RuntimeError as exc:
        summary = {'status': 'failed', 'provider': 'volcengine', 'error_code': str(exc)}
    summary['elapsed_seconds'] = round(time.monotonic()-started, 3)
    print(json.dumps(summary, ensure_ascii=False))
    if args.output:
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
