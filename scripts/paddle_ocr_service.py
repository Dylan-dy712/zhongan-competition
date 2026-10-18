"""Local persistent PaddleOCR service. Run in a separate Paddle Python environment."""
import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import threading
import time
import uuid

MAX_REQUEST_BYTES = 32 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8866)
    parser.add_argument('--model-root', type=Path, required=True, help='existing official_models directory')
    args = parser.parse_args()
    model_root = args.model_root.resolve()
    for name in ('PP-OCRv5_server_det', 'PP-OCRv5_server_rec'):
        if not (model_root / name).is_dir():
            parser.error('missing local model directory: ' + name)
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from PIL import Image
    import numpy as np
    from paddleocr import PaddleOCR
    from services.api.app.paddle_ocr import OCR_VERSION
    pipeline = PaddleOCR(ocr_version='PP-OCRv5',
        text_detection_model_name='PP-OCRv5_server_det',
        text_recognition_model_name='PP-OCRv5_server_rec',
        text_detection_model_dir=str(model_root / 'PP-OCRv5_server_det'),
        text_recognition_model_dir=str(model_root / 'PP-OCRv5_server_rec'),
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, device='cpu', cpu_threads=4, enable_mkldnn=False,
        text_det_limit_side_len=960, text_det_limit_type='max')
    lock = threading.Lock()

    def recognize(payload):
        rotation = payload.get('rotation_degrees', 0)
        if type(rotation) is not int or rotation not in (0, 90, 180, 270):
            raise ValueError('invalid rotation')
        data = base64.b64decode(payload['image_base64'], validate=True)
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 40_000_000:
                raise ValueError('image too large')
            upright = source.rotate(rotation, expand=True).convert('RGB')
        width, height = upright.size
        blocks = []
        started = time.monotonic()
        with lock:
            for result in pipeline.predict(np.asarray(upright)[:, :, ::-1].copy()):
                for text, polygon, score in zip(result['rec_texts'], result['rec_polys'], result['rec_scores']):
                    if not text.strip():
                        continue
                    xs, ys = [float(p[0]) / width for p in polygon], [float(p[1]) / height for p in polygon]
                    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                    # Restore boxes to original image coordinates, matching the other adapters.
                    box = {0: [x1, y1, x2, y2], 90: [1-y2, x1, 1-y1, x2],
                           180: [1-x2, 1-y2, 1-x1, 1-y1], 270: [y1, 1-x2, y2, 1-x1]}[rotation]
                    blocks.append({'text': text, 'bbox': [max(0., min(1., v)) for v in box],
                        'metadata': {'confidence_score': float(score), 'confidence_method': OCR_VERSION}})
        return {'text': '\n'.join(b['text'] for b in blocks), 'blocks': blocks,
                'request_id': str(uuid.uuid4()), 'angle': rotation, 'parser_version': OCR_VERSION,
                'seconds': round(time.monotonic()-started, 3), 'tables': [],
                'limits': 'CPU detection longest side 960; no table structure model; explicit rotation only'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log medical input, output, or request payloads.

        def respond(self, status, result):
            data = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.respond(200 if self.path == '/health' else 404,
                         {'status': 'ready', 'parser_version': OCR_VERSION} if self.path == '/health' else {'error': 'not_found'})

        def do_POST(self):
            if self.path != '/recognize':
                return self.respond(404, {'error': 'not_found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_REQUEST_BYTES:
                    return self.respond(413, {'error': 'invalid_request_size'})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('invalid payload')
                result = recognize(payload)
                self.respond(200, result)
            except (ValueError, KeyError, TypeError, OSError, binascii.Error):
                self.respond(400, {'error': 'invalid_image_request'})
            except Exception:
                self.respond(500, {'error': 'paddle_inference_failed'})

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    print(json.dumps({'status': 'ready', 'port': args.port, 'parser_version': OCR_VERSION}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
