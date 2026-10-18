"""Phase-one confirmed self-reports and preferences, never medical verification."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from .core import Contract

MemoryKind = Literal['communication_preference', 'confirmed_context']
MemoryField = Literal['communication_style', 'care_preference', 'followup_time',
                      'followup_location', 'medication', 'allergy', 'recovery_status']


class MemorySuggestion(Contract):
    kind: MemoryKind
    field_key: MemoryField
    content: str = Field(min_length=2, max_length=1000)

    @model_validator(mode='after')
    def kind_matches_field(self):
        if (self.kind == 'communication_preference') != (self.field_key in {'communication_style', 'care_preference'}):
            raise ValueError('Memory kind does not match field')
        return self


class MemoryCandidateCreate(MemorySuggestion):
    source_turn_id: UUID
    scope: Literal['patient', 'case'] = 'case'
    expires_at: datetime | None = None

    @field_validator('expires_at')
    @classmethod
    def aware_future(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError('Expiry must be a future timezone-aware timestamp')
        return value

    @model_validator(mode='after')
    def limit_dynamic_memory(self):
        if self.field_key in {'medication', 'recovery_status', 'followup_time', 'followup_location'}:
            if self.scope != 'case' or self.expires_at is None:
                raise ValueError('Time-sensitive statements require a case scope and explicit expiry')
        return self


class MemoryConfirm(Contract):
    confirmation: Literal[True]
    expected_version: int = Field(ge=1)
    replaces_memory_id: UUID | None = None
    replaces_version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def replacement_pair(self):
        if (self.replaces_memory_id is None) != (self.replaces_version is None):
            raise ValueError('Replacement ID and version must be supplied together')
        return self


class MemoryConsentChange(Contract):
    enabled: bool
    expected_version: int = Field(ge=0)


class ConversationMemoryChange(Contract):
    read_enabled: bool
    export_enabled: bool
    report_enabled: bool = False
    expected_version: int = Field(ge=0)

    @model_validator(mode='after')
    def report_requires_read(self):
        if self.report_enabled and not self.read_enabled:
            raise ValueError('Report memory requires conversation memory reading')
        return self


class ConversationMemoryResponse(Contract):
    read_enabled: bool
    export_enabled: bool
    report_enabled: bool
    version: int


class MemoryRevoke(Contract):
    expected_version: int = Field(ge=1)


class MemoryReference(Contract):
    memory_id: UUID
    version: int
    epoch: int


class MemorySettingsResponse(Contract):
    subject_id: UUID
    enabled: bool
    version: int
    epoch: int
    purpose: Literal['continuous_care_memory'] = 'continuous_care_memory'


class MemoryItemResponse(Contract):
    memory_id: UUID
    version: int
    kind: MemoryKind
    field_key: MemoryField
    content: str
    scope: Literal['patient', 'case']
    source_case_id: UUID
    source_turn_id: UUID
    status: str
    expires_at: datetime | None
    confirmed_at: datetime


class MemoryCandidateResponse(Contract):
    candidate_id: UUID
    version: int
    kind: MemoryKind
    field_key: MemoryField
    content: str
    scope: Literal['patient', 'case']
    case_id: UUID
    source_turn_id: UUID
    status: str
    expires_at: datetime | None


class MemoryListResponse(Contract):
    memories: list[MemoryItemResponse]
    candidates: list[MemoryCandidateResponse]


class ReportMemorySourceResponse(Contract):
    source_ref: str
    memory_id: UUID
    version: int
    kind: MemoryKind
    field_key: MemoryField
    content: str
    scope: Literal['patient','case']
    source_case_id: UUID
    source_turn_id: UUID
    source_recorded_at: datetime
    confirmed_at: datetime
    expires_at: datetime | None
    requires_reconciliation: bool
    source_kind: Literal['user_confirmed_statement'] = 'user_confirmed_statement'
    medical_verification: Literal[False] = False


class ReportMemorySourcesResponse(Contract):
    report_id: UUID
    report_version: int
    sources: list[ReportMemorySourceResponse]
