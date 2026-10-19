"""Local persistent PaddleOCR service. Run in a separate Paddle Python environment."""
import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

MAX_REQUEST_BYTES = 32 * 1024 * 1024
MODEL_NAMES = {'v5_server': ('PP-OCRv5_server_det', 'PP-OCRv5_server_rec'),
               'v6_medium': ('PP-OCRv6_medium_det', 'PP-OCRv6_medium_rec')}


def native_worker(model_root, device, det_limit, ocr_model='v5_server'):
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from PIL import Image
    import numpy as np
    from paddleocr import PaddleOCR
    from services.api.app.paddle_ocr import profile_version
    OCR_VERSION = profile_version(device, det_limit, ocr_model)
    det_name, rec_name = MODEL_NAMES[ocr_model]
    limit_type = 'min' if det_limit == 64 else 'max'
    pipeline = PaddleOCR(
        text_detection_model_name=det_name,
        text_recognition_model_name=rec_name,
        text_detection_model_dir=str(model_root / det_name),
        text_recognition_model_dir=str(model_root / rec_name),
        use_doc_orientation_classify=False, use_doc_unwarping=False,
        use_textline_orientation=False, device=device, cpu_threads=4, enable_mkldnn=False,
        text_det_limit_side_len=det_limit, text_det_limit_type=limit_type)
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
                'device': device,
                'ocr_model': ocr_model, 'detection_model': det_name, 'recognition_model': rec_name,
                'limits': f'Detection {limit_type} side {det_limit}, max_side_limit 4000; no tables; explicit rotation only'}

    print('_PADDLE_RESULT_' + json.dumps({'status': 'ready'}), flush=True)
    for line in sys.stdin:
        try:
            result = {'result': recognize(json.loads(line))}
        except (ValueError, KeyError, TypeError, OSError, binascii.Error):
            result = {'error': 'invalid_image_request'}
        except Exception:
            result = {'error': 'paddle_inference_failed'}
        print('_PADDLE_RESULT_' + json.dumps(result, ensure_ascii=True), flush=True)


class PaddleProcess:
    """One persistent native worker; a native crash/timeout cannot block later pages."""
    def __init__(self, model_root, timeout, device, det_limit, ocr_model='v5_server'):
        self.model_root, self.timeout = model_root, timeout
        self.device = device
        self.det_limit = det_limit
        self.ocr_model = ocr_model
        self.lock = threading.Lock()
        self.process = None
        self.start()

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=10)
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None

    def start(self):
        self.messages = queue.Queue()
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        self.process = subprocess.Popen([sys.executable, '-u', '-m', 'scripts.paddle_ocr_service',
            '--model-root', str(self.model_root), '--device', self.device,
            '--det-limit', str(self.det_limit), '--ocr-model', self.ocr_model, '--native-worker'], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, encoding='utf-8', **options)
        def read(process, messages):
            try:
                for line in process.stdout:
                    if line.startswith('_PADDLE_RESULT_'):
                        messages.put(json.loads(line[len('_PADDLE_RESULT_'):]))
            except (ValueError, OSError):
                pass
            finally:
                messages.put({'error': 'paddle_native_exited'})
        threading.Thread(target=read, args=(self.process, self.messages), daemon=True).start()
        try:
            if self.messages.get(timeout=90).get('status') != 'ready':
                raise RuntimeError('PADDLE_NATIVE_START_FAILED')
        except (queue.Empty, RuntimeError):
            self.stop()
            raise RuntimeError('PADDLE_NATIVE_START_FAILED') from None

    def recognize(self, payload):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.stop()
                self.start()
            try:
                self.process.stdin.write(json.dumps(payload, ensure_ascii=True) + '\n')
                self.process.stdin.flush()
                response = self.messages.get(timeout=self.timeout)
            except queue.Empty:
                self.stop()
                raise TimeoutError('PADDLE_NATIVE_TIMEOUT') from None
            except (BrokenPipeError, OSError):
                self.stop()
                raise RuntimeError('PADDLE_NATIVE_EXITED') from None
            if 'result' not in response:
                if response.get('error') == 'invalid_image_request':
                    raise ValueError('invalid image')
                self.stop()
                raise RuntimeError('PADDLE_NATIVE_FAILED')
            response['result']['native_timeout_seconds'] = self.timeout
            return response['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8866)
    parser.add_argument('--model-root', type=Path, required=True, help='existing official_models directory')
    parser.add_argument('--native-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--page-timeout', type=int, default=300)
    parser.add_argument('--device', choices=['cpu', 'gpu:0'], default='cpu')
    parser.add_argument('--det-limit', type=int, choices=[64, 960, 1600], default=960)
    parser.add_argument('--ocr-model', choices=sorted(MODEL_NAMES), default='v5_server')
    args = parser.parse_args()
    model_root = args.model_root.resolve()
    for name in MODEL_NAMES[args.ocr_model]:
        if not (model_root / name).is_dir():
            parser.error('missing local model directory: ' + name)
    if not 1 <= args.page_timeout <= 480:
        parser.error('page-timeout must be between 1 and 480 seconds')
    if args.device == 'cpu' and args.det_limit != 960:
        parser.error('CPU retains the previously verified 960 limit; higher resolution is GPU-only')
    from services.api.app.paddle_ocr import profile_version
    OCR_VERSION = profile_version(args.device, args.det_limit, args.ocr_model)
    if args.native_worker:
        native_worker(model_root, args.device, args.det_limit, args.ocr_model)
        return
    worker = PaddleProcess(model_root, args.page_timeout, args.device, args.det_limit, args.ocr_model)

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
                         {'status': 'ready', 'parser_version': OCR_VERSION,
                          'native_worker_ready': worker.process is not None and worker.process.poll() is None,
                          'busy': worker.lock.locked()} if self.path == '/health' else {'error': 'not_found'})

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
                result = worker.recognize(payload)
                self.respond(200, result)
            except TimeoutError:
                self.respond(504, {'error': 'paddle_native_timeout'})
            except RuntimeError:
                self.respond(503, {'error': 'paddle_native_unavailable'})
            except (ValueError, KeyError, TypeError, OSError, binascii.Error):
                self.respond(400, {'error': 'invalid_image_request'})
            except Exception:
                self.respond(500, {'error': 'paddle_inference_failed'})

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    print(json.dumps({'status': 'ready', 'port': args.port, 'parser_version': OCR_VERSION}), flush=True)
    try:
        server.serve_forever()
    finally:
        worker.stop()


if __name__ == '__main__':
    main()
