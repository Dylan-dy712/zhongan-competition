"""REQ-01～04 shared data semantics from spec.md v0.1.0."""

from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldStatus(str, Enum):
    observed = "observed"
    derived = "derived"
    missing = "missing"
    unreadable = "unreadable"
    conflict = "conflict"
    not_applicable = "not_applicable"


class Assertion(str, Enum):
    present = "present"
    negated = "negated"
    suspected = "suspected"
    historical = "historical"
    unknown = "unknown"


class DataOrigin(str, Enum):
    official_deidentified = "official_deidentified"
    authorized_historical = "authorized_historical"
    synthetic = "synthetic"


class ExecutionMode(str, Enum):
    live = "live"
    mock = "mock"
    replay = "replay"


class TextSpan(Contract):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    offset_unit: str = "unicode_code_point"

    @model_validator(mode="after")
    def valid_range(self):
        if self.end <= self.start or self.offset_unit != "unicode_code_point":
            raise ValueError("invalid Unicode code point span")
        return self


class Evidence(Contract):
    evidence_id: UUID
    case_id: UUID
    document_id: UUID
    document_version: int = Field(ge=1)
    page_index: int | None = Field(default=None, ge=0)
    text_span: TextSpan | None = None
    bbox: tuple[float, float, float, float] | None = None
    extraction_method: str
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_version: str
    schema_version: str = "0.1.0"

    @model_validator(mode="after")
    def valid_bbox(self):
        if self.bbox is not None:
            x0, y0, x1, y1 = self.bbox
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError("bbox must be normalized and ordered")
        return self


T = TypeVar("T")


class FieldCandidate(Contract, Generic[T]):
    value: T
    evidence_ids: list[UUID] = Field(min_length=1)


class FieldValue(Contract, Generic[T]):
    field_id: UUID
    value: T | None
    raw_value: str | None
    status: FieldStatus
    evidence_ids: list[UUID]
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    confidence_method: str | None = None
    unit: str | None = None
    derivation: dict | None = None
    alternatives: list[FieldCandidate[T]] = Field(default_factory=list)
    missing_reason: str | None = None

    @model_validator(mode="after")
    def check_semantics(self):
        if self.confidence_score is not None and not self.confidence_method:
            raise ValueError("confidence_method required with score")
        if self.status == FieldStatus.conflict:
            if self.value is not None or len(self.alternatives) < 2:
                raise ValueError("conflict requires unresolved value and sourced alternatives")
        elif self.alternatives:
            raise ValueError("alternatives only allowed for conflict")
        if self.status in {FieldStatus.missing, FieldStatus.unreadable, FieldStatus.not_applicable} and self.value is not None:
            raise ValueError("unknown or inapplicable value must be null")
        if self.status == FieldStatus.derived and not self.derivation:
            raise ValueError("derived value requires derivation")
        if self.status == FieldStatus.observed and (self.value is None or not self.evidence_ids):
            raise ValueError("observed value requires value and evidence")
        return self


class ExtractedFact(FieldValue[object]):
    fact_type: str
    run_id: UUID
    case_id: UUID
    assertion: Assertion
    extractor_version: str
    schema_version: str = "0.1.0"


class Money(Contract):
    amount_minor: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class EventTime(Contract):
    start: str
    end: str | None = None
    timezone: str | None = None


class EventRelation(Contract):
    from_event_id: UUID
    relation_type: str
    to_ref: dict[str, str]
    evidence_ids: list[UUID]
    status: str


class MedicalEvent(Contract):
    event_id: UUID
    case_id: UUID
    encounter_id: UUID
    event_type: str
    assertion: Assertion
    occurred_at: EventTime | None
    time_precision: str
    attributes: dict
    evidence_ids: list[UUID]
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    related_event_ids: list[UUID] = Field(default_factory=list)
    schema_version: str = "0.1.0"


class ExternalRef(Contract):
    source_system: str
    external_id: str


class Case(Contract):
    case_id: UUID
    subject_id: UUID
    external_case_ref: ExternalRef | None
    consent_refs: list[UUID]
    data_origin: DataOrigin
    user_context: dict | None
    version: int = Field(ge=1)
    created_at: datetime
    schema_version: str = "0.1.0"


class Document(Contract):
    document_id: UUID
    case_id: UUID
    document_version: int = Field(ge=1)
    document_type: str | None
    media_type: str
    byte_size: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=0)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_ref: str
    status: str
    policy_version: str
    created_at: datetime
    schema_version: str = "0.1.0"


class DocumentVersionRef(Contract):
    document_id: UUID
    document_version: int = Field(ge=1)


class AnalysisRun(Contract):
    run_id: UUID
    case_id: UUID
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: str
    pipeline_version: str
    document_versions: list[DocumentVersionRef] = Field(min_length=1)
    status: str
    current_stage: str
    stage_results: dict
    attempt: int = Field(ge=0)
    max_attempts: int = Field(gt=0)
    error: dict | None
    execution_mode: ExecutionMode
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
