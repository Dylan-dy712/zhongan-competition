"""PaddleOCR sidecar adapter; model packages are isolated from the API runtime."""
import base64
import os
from urllib.parse import urlparse
import requests

OCR_METHOD = 'paddle_ocr_v5_server'
OCR_VERSION = 'paddle-ocr-v5-server-cpu-960-v1'


class PaddleOcr:
    method = OCR_METHOD
    version = OCR_VERSION

    def __init__(self):
        self.url = os.getenv('ZHONGAN_PADDLE_OCR_URL', 'http://127.0.0.1:8866').rstrip('/')
        parsed = urlparse(self.url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise RuntimeError('PADDLE_OCR_REQUIRES_LOOPBACK_URL')

    def recognize(self, image_bytes, width, height, *, rotation_degrees=0):
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.post(self.url + '/recognize', json={
                    'image_base64': base64.b64encode(image_bytes).decode('ascii'),
                    'rotation_degrees': rotation_degrees}, timeout=(5, 600))
                if response.status_code == 504:
                    raise RuntimeError('PADDLE_OCR_NATIVE_TIMEOUT')
                response.raise_for_status()
                result = response.json()
            if result.get('parser_version') != self.version:
                raise RuntimeError('PADDLE_OCR_VERSION_MISMATCH')
            if not isinstance(result.get('text'), str) or not isinstance(result.get('blocks'), list):
                raise RuntimeError('PADDLE_OCR_INVALID_RESULT')
            return result
        except (requests.RequestException, ValueError):
            raise RuntimeError('PADDLE_OCR_SERVICE_UNAVAILABLE') from None
