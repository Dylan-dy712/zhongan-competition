"""Explicit OCR provider selection. A failed request never switches billing providers."""
import os
from typing import Protocol

from .tencent_ocr import OCR_METHOD, OCR_VERSION, TABLE_OCR_METHOD, TABLE_OCR_VERSION, TencentOcr, TencentTableOcr
from .volcengine_ocr import VolcengineOcr
from .material_routing import route_material
from .paddle_ocr import PaddleOcr, OCR_VERSIONS as PADDLE_OCR_VERSIONS, GPU_HIGH_RES_VERSION


def recognize_routed(ocr, image_bytes, width, height, *, enable_table=False, use_new_model=False):
    result = ocr.recognize(image_bytes, width, height)
    routing = route_material(result['text'])
    result['material_routing'] = routing
    result['table_routing'] = {'status': 'not_requested'}
    if result.get('tables'):
        result['table_routing'] = {'status': 'available', 'primary_table_ocr': True,
                                   'request_id': result['request_id']}
        return result
    if not enable_table or routing['ocr_strategy'] != 'table':
        return result
    if not callable(getattr(ocr, 'recognize_table', None)):
        result['table_routing'] = {'status': 'unsupported', 'requires_review': True}
        return result
    try:
        table = ocr.recognize_table(image_bytes, width, height, use_new_model=use_new_model)
        result['tables'] = table['tables']
        result['table_routing'] = {'status': 'available' if table['tables'] else 'empty',
            'request_id': table['request_id'], 'requires_review': not bool(table['tables'])}
    except RuntimeError as exc:
        # Keep general OCR and never silently switch to another billing provider.
        result['table_routing'] = {'status': 'unavailable', 'error_code': type(exc).__name__,
                                   'requires_review': True}
    return result


class Ocr(Protocol):
    method: str
    version: str

    def recognize(self, image_bytes: bytes, width: int, height: int) -> dict: ...


def create_ocr(provider: str | None = None) -> Ocr:
    provider = (provider if provider is not None else os.environ.get('ZHONGAN_OCR_PROVIDER', 'tencent')).strip().lower()
    if provider == 'tencent':
        return TencentOcr()
    if provider == 'tencent_table':
        return TencentTableOcr()
    if provider == 'volcengine':
        return VolcengineOcr()
    if provider == 'paddle':
        return PaddleOcr()
    raise RuntimeError('OCR_PROVIDER_NOT_SUPPORTED')


def provider_ocr_version(provider):
    if provider == 'paddle':
        return PaddleOcr().version
    versions = {'tencent': OCR_VERSION, 'tencent_table': TABLE_OCR_VERSION,
                'volcengine': VolcengineOcr.version, 'paddle': PaddleOcr.version}
    if provider not in versions:
        raise RuntimeError('OCR_PROVIDER_NOT_SUPPORTED')
    return versions[provider]


def page_ocr_method(page: dict) -> str | None:
    return {OCR_VERSION: OCR_METHOD, TABLE_OCR_VERSION: TABLE_OCR_METHOD,
            **{version: PaddleOcr.method for version in PADDLE_OCR_VERSIONS.values()},
            GPU_HIGH_RES_VERSION: PaddleOcr.method,
            VolcengineOcr.version: VolcengineOcr.method}.get(page.get('parser_version'))
