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


class EventBundle(Contract):
    case_id: UUID
    run_id: UUID
    events: list[MedicalEvent]
    relations: list[EventRelation]
    builder_version: str
    schema_version: str = "0.1.0"


class InsightCategory(str, Enum):
    clinical = "clinical"
    cost = "cost"
    experience = "experience"


class Insight(Contract):
    insight_id: UUID
    case_id: UUID
    run_id: UUID
    category: InsightCategory
    label: str
    severity: str = Field(pattern=r"^(low|medium|high|undetermined)$")
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_method: str | None = None
    evidence_ids: list[UUID] = Field(min_length=1)
    rationale: str
    uncertainty: str | None = None
    suggested_action: str
    review_required: bool
    review_status: str = Field(pattern=r"^(not_required|pending|approved|corrected|rejected)$")
    judgment_status: str = Field(pattern=r"^(candidate|supported|indeterminate|rejected)$")
    rule_version: str
    knowledge_refs: list[str] = Field(default_factory=list)
    schema_version: str = "0.1.0"

    @model_validator(mode="after")
    def validate_review_semantics(self):
        if self.category == InsightCategory.clinical and self.review_status == "not_required":
            raise ValueError("clinical insight candidates require review")
        if self.confidence is not None and not self.confidence_method:
            raise ValueError("confidence_method required with confidence")
        return self


class ReviewCorrection(Contract):
    field_or_claim_id: str = Field(pattern=r"^(severity|rationale|uncertainty|suggested_action|judgment_status|knowledge_refs)$")
    replacement: object
    source_refs: list[UUID] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=1000)


class ReviewTask(Contract):
    review_id: UUID
    case_id: UUID
    run_id: UUID
    target_type: str = Field(pattern=r"^insight$")
    target_id: UUID
    target_version: int = Field(ge=1)
    status: str = Field(pattern=r"^(pending|decided|cancelled)$")
    reason: str
    target: Insight
    created_at: datetime


class ReviewDecision(Contract):
    decision_id: UUID
    review_id: UUID
    target_type: str
    target_id: UUID
    target_version: int
    decision: str = Field(pattern=r"^(approve|correct|reject)$")
    reason: str
    corrections: list[ReviewCorrection] = Field(default_factory=list)
    reviewer_id: UUID
    decided_at: datetime


class Claim(Contract):
    claim_id: UUID
    text: str = Field(min_length=1, max_length=3000)
    claim_type: str = Field(pattern=r"^(case_fact|professional_explanation|patient_statement|service_suggestion|to_confirm)$")
    evidence_refs: list[UUID] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    review_status: str = Field(pattern=r"^(not_required|pending|approved|corrected|rejected)$")

    @model_validator(mode="after")
    def source_required(self):
        if self.claim_type == "case_fact" and not self.evidence_refs:
            raise ValueError("case_fact requires evidence_refs")
        if self.claim_type == "professional_explanation" and not self.knowledge_refs:
            raise ValueError("professional_explanation requires knowledge_refs")
        if self.claim_type == "patient_statement" and not self.source_refs:
            raise ValueError("patient_statement requires source_refs")
        return self


class ReportSection(Contract):
    section_type: str = Field(pattern=r"^(diagnosis_explanation|treatment_review|cost_explanation|recovery_plan|emotional_support|next_visit_advice)$")
    claims: list[Claim] = Field(min_length=1)


class Action(Contract):
    action_id: UUID
    report_id: UUID
    source_refs: list[str] = Field(min_length=1)
    owner_role: str = Field(pattern=r"^(patient|caregiver|clinician|customer_service)$")
    action_text: str = Field(min_length=1, max_length=1000)
    due_at: str | None = None
    due_source: str = Field(pattern=r"^(medical_order|user_request|service_policy|unknown)$")
    status: str = Field(pattern=r"^(proposed|acknowledged|completed|deferred|help_requested|cancelled)$")
    feedback_ref: UUID | None = None
    priority: int = Field(ge=1, le=3)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def due_time_has_source(self):
        if self.due_at is not None and self.due_source == "unknown":
            raise ValueError("due_at requires a known due_source")
        if self.due_at is not None:
            if "T" not in self.due_at or datetime.fromisoformat(self.due_at).tzinfo is None:
                raise ValueError("due_at requires an RFC3339 timestamp with timezone")
        return self


class ConsentUse(Contract):
    consent_id: UUID
    version: int = Field(ge=1)
    purpose: str


class Report(Contract):
    report_id: UUID
    case_id: UUID
    run_id: UUID
    report_version: int = Field(ge=1)
    status: str = Field(pattern=r"^(draft|validating|ready|pending_review|rejected|published|superseded|invalidated)$")
    sections: list[ReportSection]
    actions: list[Action] = Field(max_length=3)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_id: str
    prompt_version: str
    knowledge_version: str
    policy_version: str
    memory_refs: list[str] = Field(default_factory=list)
    consent_refs: list[ConsentUse] = Field(min_length=1)
    validation_errors: list[str] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def six_sections_exactly_once(self):
        expected = {"diagnosis_explanation", "treatment_review", "cost_explanation",
                    "recovery_plan", "emotional_support", "next_visit_advice"}
        actual = [s.section_type for s in self.sections]
        if len(actual) != 6 or set(actual) != expected:
            raise ValueError("report requires six unique sections")
        return self


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
