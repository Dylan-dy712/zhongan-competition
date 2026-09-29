"""通用契约：状态枚举、证据、FieldValue。

对应规格 docs/spec.md §5。本文件是可执行契约的唯一源，
导出的 JSON Schema 供前端与评测使用，不允许另立手写 Schema。
"""

from __future__ import annotations

import enum
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def new_id() -> str:
    return str(uuid.uuid4())


class DataOrigin(str, enum.Enum):
    official_deidentified = "official_deidentified"
    authorized_historical = "authorized_historical"
    synthetic = "synthetic"


class ExecutionMode(str, enum.Enum):
    live = "live"
    mock = "mock"
    replay = "replay"


class FieldStatus(str, enum.Enum):
    observed = "observed"
    derived = "derived"
    missing = "missing"
    unreadable = "unreadable"
    conflict = "conflict"
    not_applicable = "not_applicable"


class Assertion(str, enum.Enum):
    present = "present"
    negated = "negated"
    suspected = "suspected"
    historical = "historical"
    unknown = "unknown"


class TimePrecision(str, enum.Enum):
    datetime = "datetime"
    day = "day"
    month = "month"
    year = "year"
    interval = "interval"
    unknown = "unknown"


class TextSpan(BaseModel):
    start: int
    end: int  # 左闭右开
    text: str
    offset_unit: Literal["unicode_code_point"] = "unicode_code_point"


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=new_id)
    case_id: str
    document_id: str
    document_version: int = 1
    page_index: int | None = None
    line_index: int | None = None  # OCR 行号（0 起），text_span 的定位载体
    text_span: TextSpan | None = None
    bbox: list[float | None] | None = None  # [x0,y0,x1,y1] 归一化 [0,1]
    extraction_method: str = "ocr_rapidocr"
    source_hash: str = ""
    parser_version: str = ""


class FieldCandidate(BaseModel):
    value: Any = None
    evidence_ids: list[str] = []
    note: str | None = None


class FieldValue(BaseModel):
    """规格 §5.2：字段级事实。value 缺失时必须给出状态，不用空串冒充。"""

    model_config = ConfigDict(validate_assignment=True)

    field_id: str = Field(default_factory=new_id)
    value: Any = None
    raw_value: str | None = None
    status: FieldStatus = FieldStatus.missing
    evidence_ids: list[str] = []
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    confidence_method: str | None = None
    unit: str | None = None
    derivation: dict[str, Any] | None = None
    alternatives: list[FieldCandidate] = []
    missing_reason: str | None = None

    @model_validator(mode="after")
    def _score_has_method(self) -> "FieldValue":
        if self.confidence_score is not None and not self.confidence_method:
            raise ValueError("confidence_score 存在时必须给出 confidence_method")
        return self

    @staticmethod
    def observed(
        value: Any,
        raw: str | None,
        evidence_ids: list[str],
        confidence: float,
        method: str,
        unit: str | None = None,
    ) -> "FieldValue":
        return FieldValue(
            value=value,
            raw_value=raw,
            status=FieldStatus.observed,
            evidence_ids=evidence_ids,
            confidence_score=confidence,
            confidence_method=method,
            unit=unit,
        )

    @staticmethod
    def missing(reason: str) -> "FieldValue":
        return FieldValue(status=FieldStatus.missing, missing_reason=reason)
