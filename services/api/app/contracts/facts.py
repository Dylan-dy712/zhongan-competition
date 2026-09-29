"""事实层契约：五类关键字段 + 就医事件（规格 §5.4～5.5）。

所有临床取值都是 FieldValue，携带状态、置信度与证据引用；
实体对象只负责组装，不重复定义字段语义。
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field

from .common import (
    Assertion,
    DataOrigin,
    Evidence,
    ExecutionMode,
    FieldValue,
    TimePrecision,
    new_id,
)


class Encounter(BaseModel):
    """一次就医（住院或门诊）的事件组容器。"""

    encounter_id: str = Field(default_factory=new_id)
    kind: str = "hospitalization"  # hospitalization | outpatient
    hospital: FieldValue | None = None
    department: FieldValue | None = None
    admission_date: FieldValue | None = None  # 门诊时为就诊日期
    discharge_date: FieldValue | None = None
    stay_days: FieldValue | None = None  # raw + derived（冻结口径：出院-入院，同日计 1）
    attending_doctor: FieldValue | None = None


class DiagnosisItem(BaseModel):
    diagnosis_id: str = Field(default_factory=new_id)
    encounter_id: str
    role: str  # admission | discharge | outpatient | pathology | comorbidity
    name: FieldValue
    icd_code: FieldValue | None = None
    assertion: Assertion = Assertion.present
    is_primary: bool = False


class ProcedureItem(BaseModel):
    procedure_id: str = Field(default_factory=new_id)
    encounter_id: str
    name: FieldValue
    performed_at: FieldValue | None = None
    time_precision: TimePrecision = TimePrecision.unknown
    surgeon: FieldValue | None = None
    anesthesia: FieldValue | None = None


class MedicationItem(BaseModel):
    medication_id: str = Field(default_factory=new_id)
    encounter_id: str
    name: FieldValue
    dosage: FieldValue | None = None
    frequency: FieldValue | None = None
    route: FieldValue | None = None
    duration_days: FieldValue | None = None
    phase: str = "inpatient"  # inpatient | discharge_prescription | outpatient


class ExpenseScope(str, enum.Enum):
    total = "total"  # 医疗总费用
    category_total = "category_total"  # 分类合计（药品费/检查费…）
    self_paid = "self_paid"  # 结算口径自付（医院端）
    insurance_paid = "insurance_paid"  # 医保统筹等支付
    out_of_catalog = "out_of_catalog"  # 自费/目录外金额
    commercial_paid = "commercial_paid"  # 商保赔付


class ExpenseItem(BaseModel):
    expense_id: str = Field(default_factory=new_id)
    encounter_id: str
    scope: ExpenseScope
    category: FieldValue | None = None  # 药品费/手术费/检查费…
    amount_minor: FieldValue | None = None  # 分；unit=CNY-minor
    document_id: str = ""
    note: str | None = None


class Completeness(BaseModel):
    diagnoses: str = "not_processed"  # found | none_applicable | not_found | not_processed
    procedures: str = "not_processed"
    medications: str = "not_processed"
    hospitalizations: str = "not_processed"
    expenses: str = "not_processed"


class MedicalEvent(BaseModel):
    """规格 §5.4：医疗事件（用于时间线重建与关系校验）。"""

    event_id: str = Field(default_factory=new_id)
    case_id: str
    encounter_id: str
    event_type: str  # diagnosis | admission | discharge | procedure | medication | examination | charge
    ref_id: str  # 指向对应 Item 的 ID
    assertion: Assertion = Assertion.present
    occurred_at: dict | None = None  # {start,end,timezone}
    time_precision: TimePrecision = TimePrecision.unknown
    label: str = ""


class CaseFacts(BaseModel):
    case_id: str
    run_id: str
    schema_version: str = "0.1.0"
    data_origin: DataOrigin = DataOrigin.official_deidentified
    execution_mode: ExecutionMode = ExecutionMode.live
    evidences: list[Evidence] = []
    encounters: list[Encounter] = []
    diagnoses: list[DiagnosisItem] = []
    procedures: list[ProcedureItem] = []
    medications: list[MedicationItem] = []
    expenses: list[ExpenseItem] = []
    events: list[MedicalEvent] = []
    completeness: Completeness = Completeness()

    def evidence_by_id(self) -> dict:
        return {e.evidence_id: e for e in self.evidences}
