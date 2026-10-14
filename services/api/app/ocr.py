"""Explicit OCR provider selection. A failed request never switches billing providers."""
import os
from typing import Protocol

from .tencent_ocr import OCR_METHOD, OCR_VERSION, TencentOcr
from .volcengine_ocr import VolcengineOcr


class Ocr(Protocol):
    method: str
    version: str

    def recognize(self, image_bytes: bytes, width: int, height: int) -> dict: ...


def create_ocr(provider: str | None = None) -> Ocr:
    provider = (provider if provider is not None else os.environ.get('ZHONGAN_OCR_PROVIDER', 'tencent')).strip().lower()
    if provider == 'tencent':
        return TencentOcr()
    if provider == 'volcengine':
        return VolcengineOcr()
    raise RuntimeError('OCR_PROVIDER_NOT_SUPPORTED')


def page_ocr_method(page: dict) -> str | None:
    return {OCR_VERSION: OCR_METHOD, VolcengineOcr.version: VolcengineOcr.method}.get(page.get('parser_version'))
