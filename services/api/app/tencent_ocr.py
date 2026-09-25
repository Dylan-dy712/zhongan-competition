"""Tencent Cloud OCR adapter. Raw document content is never logged."""

import base64
import os
import time

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.ocr.v20181119 import models, ocr_client


OCR_METHOD = "tencent_general_accurate_ocr"
OCR_VERSION = "tencent-ocr-2018-11-19-general-accurate-v1"
RETRYABLE_CODES = {
    "FailedOperation.EngineRecognizeTimeout",
    "FailedOperation.OcrFailed",
    "InternalError",
    "RequestLimitExceeded",
}


def normalize_bbox(item, width: int, height: int):
    polygon = getattr(item, "Polygon", None) or []
    if not polygon or width <= 0 or height <= 0:
        return None
    xs = [point.X for point in polygon]
    ys = [point.Y for point in polygon]
    clamp = lambda value: max(0.0, min(1.0, value))
    return [clamp(min(xs) / width), clamp(min(ys) / height),
            clamp(max(xs) / width), clamp(max(ys) / height)]


class TencentOcr:
    def __init__(self):
        secret_id = os.environ.get("TENCENTCLOUD_SECRET_ID")
        secret_key = os.environ.get("TENCENTCLOUD_SECRET_KEY")
        if not secret_id or not secret_key:
            raise RuntimeError("OCR_NOT_CONFIGURED")
        region = os.environ.get("TENCENTCLOUD_REGION", "ap-guangzhou")
        http = HttpProfile(endpoint="ocr.tencentcloudapi.com", reqTimeout=20)
        profile = ClientProfile(httpProfile=http)
        self.client = ocr_client.OcrClient(
            credential.Credential(secret_id, secret_key), region, profile
        )

    def recognize(self, image_bytes: bytes, width: int, height: int):
        request = models.GeneralAccurateOCRRequest()
        request.ImageBase64 = base64.b64encode(image_bytes).decode("ascii")
        request.IsWords = False
        response = None
        for attempt in range(3):
            try:
                response = self.client.GeneralAccurateOCR(request)
                break
            except TencentCloudSDKException as exc:
                if exc.code not in RETRYABLE_CODES or attempt == 2:
                    raise RuntimeError(f"OCR_PROVIDER_ERROR:{exc.code}") from None
                time.sleep(2 ** attempt)
        blocks = []
        for order, item in enumerate(response.TextDetections or []):
            value = (item.DetectedText or "").strip()
            if not value:
                continue
            blocks.append({
                "type": "paragraph", "order": order, "text": value,
                "bbox": normalize_bbox(item, width, height),
                "metadata": {
                    "confidence_score": (item.Confidence / 100.0) if item.Confidence is not None else None,
                    "confidence_method": OCR_VERSION,
                },
            })
        return {
            "text": "\n".join(block["text"] for block in blocks),
            "blocks": blocks,
            "request_id": response.RequestId,
            "angle": response.Angle,
        }
