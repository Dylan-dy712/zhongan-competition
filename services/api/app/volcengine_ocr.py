"""Volcengine OCRNormal adapter. Never log credentials or document content.

API: https://www.volcengine.com/docs/86081/1660261?lang=en
Signature follows the official volc-sdk-python SignerV4 implementation.
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import math
import os
import re
from urllib.parse import urlencode

import requests
from .ocr_throttle import ocr_request_slot

HOST = 'visual.volcengineapi.com'
QUERY = 'Action=OCRNormal&Version=2020-08-26'
CONTENT_TYPE = 'application/x-www-form-urlencoded; charset=utf-8'


def signed_headers(body: bytes, access_key: str, secret_key: str, token: str = '', timestamp: str | None = None):
    timestamp = timestamp or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    digest = hashlib.sha256(body).hexdigest()
    headers = {'Content-Type': CONTENT_TYPE, 'Host': HOST, 'X-Date': timestamp, 'X-Content-Sha256': digest}
    if token:
        headers['X-Security-Token'] = token
    canonical_headers = {key.lower(): value for key, value in headers.items()}
    names = ';'.join(sorted(canonical_headers))
    values = ''.join(key+':'+canonical_headers[key]+'\n' for key in sorted(canonical_headers))
    canonical_request = '\n'.join(['POST', '/', QUERY, values, names, digest])
    scope = timestamp[:8]+'/cn-north-1/cv/request'
    signing_string = '\n'.join(['HMAC-SHA256', timestamp, scope, hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()])
    key = secret_key.encode('utf-8')
    for part in [timestamp[:8], 'cn-north-1', 'cv', 'request']:
        key = hmac.new(key, part.encode('utf-8'), hashlib.sha256).digest()
    signature = hmac.new(key, signing_string.encode('utf-8'), hashlib.sha256).hexdigest()
    headers['Authorization'] = f'HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={names}, Signature={signature}'
    return headers


def normalize_bbox(rect, width, height):
    if not isinstance(rect, dict) or width <= 0 or height <= 0:
        return None
    values = [rect.get(key) for key in ('x', 'y', 'width', 'height')]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values):
        return None
    x, y, w, h = values
    if w < 0 or h < 0:
        return None
    clamp = lambda value: max(0.0, min(1.0, value))
    return [clamp(x/width), clamp(y/height), clamp((x+w)/width), clamp((y+h)/height)]


def normalize_response(payload: dict, width: int, height: int):
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('line_texts'), list):
        raise RuntimeError('OCR_PROVIDER_ERROR:INVALID_RESPONSE')
    rects, scores = data.get('line_rects') or [], data.get('line_probs') or []
    if not isinstance(rects, list) or not isinstance(scores, list):
        raise RuntimeError('OCR_PROVIDER_ERROR:INVALID_RESPONSE')
    blocks = []
    for index, value in enumerate(data['line_texts']):
        if not isinstance(value, str):
            raise RuntimeError('OCR_PROVIDER_ERROR:INVALID_RESPONSE')
        value = value.strip()
        if not value:
            continue
        score = scores[index] if index < len(scores) else None
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
            score = None
        blocks.append({'type': 'paragraph', 'order': len(blocks), 'text': value,
                       'bbox': normalize_bbox(rects[index], width, height) if index < len(rects) else None,
                       'metadata': {'confidence_score': score, 'confidence_method': VolcengineOcr.version}})
    return {'text': '\n'.join(block['text'] for block in blocks), 'blocks': blocks,
            'request_id': payload.get('request_id'), 'angle': None}


class VolcengineOcr:
    method = 'volcengine_ocr_normal'
    version = 'volcengine-ocr-2020-08-26-normal-v1'

    def __init__(self):
        self.access_key = os.environ.get('VOLCENGINE_OCR_ACCESS_KEY_ID', '').strip()
        self.secret_key = os.environ.get('VOLCENGINE_OCR_SECRET_ACCESS_KEY', '').strip()
        self.token = os.environ.get('VOLCENGINE_OCR_SECURITY_TOKEN', '').strip()
        if not self.access_key or not self.secret_key:
            raise RuntimeError('OCR_NOT_CONFIGURED')

    def recognize(self, image_bytes: bytes, width: int, height: int):
        if not image_bytes or width <= 0 or height <= 0:
            raise RuntimeError('OCR_PROVIDER_ERROR:INVALID_IMAGE')
        body = urlencode({'image_base64': base64.b64encode(image_bytes).decode('ascii'),
                          'mode': 'default', 'filter_thresh': '0', 'half_to_full': 'false'}).encode('ascii')
        if len(body) > 8*1024*1024:
            raise RuntimeError('OCR_PROVIDER_ERROR:IMAGE_TOO_LARGE')
        # One request: avoid duplicate charges when an upstream times out.
        try:
            with ocr_request_slot(os.environ.get('ZHONGAN_OCR_RATE_LIMIT_FILE')):
                response = requests.post('https://'+HOST+'/?'+QUERY, data=body,
                                         headers=signed_headers(body, self.access_key, self.secret_key, self.token),
                                         # Requests also uses the connection timeout while writing the form.
                                         # Full-resolution scan pages take >5s on the deployed outbound link.
                                         timeout=(90, 30), allow_redirects=False)
        except requests.Timeout:
            raise RuntimeError('OCR_PROVIDER_ERROR:TIMEOUT') from None
        except requests.RequestException:
            raise RuntimeError('OCR_PROVIDER_ERROR:NETWORK') from None
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError('OCR_PROVIDER_ERROR:INVALID_RESPONSE') from None
        if not isinstance(payload, dict):
            raise RuntimeError('OCR_PROVIDER_ERROR:INVALID_RESPONSE')
        if response.status_code != 200 or payload.get('code') != 10000:
            code = payload.get('code')
            metadata = payload.get('ResponseMetadata') or {}
            if isinstance(metadata, dict) and isinstance(metadata.get('Error'), dict):
                code = metadata['Error'].get('Code', code)
            # Provider messages can include submitted data. Retain only a bounded code.
            code = str(code) if code is not None else 'HTTP_'+str(response.status_code)
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', code):
                code = 'HTTP_'+str(response.status_code)
            raise RuntimeError('OCR_PROVIDER_ERROR:'+code)
        return normalize_response(payload, width, height)
