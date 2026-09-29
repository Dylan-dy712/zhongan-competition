"""温度指引契约：六段式报告、事实声明、优先行动（规格 §6.4）。"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field

from .common import new_id

SECTION_KEYS = [
    "diagnosis_explanation",
    "treatment_review",
    "cost_explanation",
    "recovery_plan",
    "emotional_support",
    "next_visit_advice",
]

SECTION_ZH = {
    "diagnosis_explanation": "诊断通俗解释",
    "treatment_review": "治疗过程回顾",
    "cost_explanation": "费用解读",
    "recovery_plan": "康复计划",
    "emotional_support": "心理安抚",
    "next_visit_advice": "下次就医建议",
}


class ClaimType(str, enum.Enum):
    case_fact = "case_fact"
    professional_explanation = "professional_explanation"
    patient_statement = "patient_statement"
    service_suggestion = "service_suggestion"
    to_confirm = "to_confirm"


class ReportClaim(BaseModel):
    """报告中的每条事实/解释声明需可溯源。"""

    claim_id: str = Field(default_factory=new_id)
    text: str
    claim_type: ClaimType
    evidence_refs: list[str] = []  # evidence_id / field_id
    knowledge_refs: list[str] = []  # 知识库条目版本化引用
    section: str = ""


class OwnerRole(str, enum.Enum):
    patient = "patient"
    caregiver = "caregiver"
    clinician = "clinician"
    customer_service = "customer_service"


class DueSource(str, enum.Enum):
    medical_order = "medical_order"
    user_request = "user_request"
    service_policy = "service_policy"
    unknown = "unknown"


class ActionStatus(str, enum.Enum):
    proposed = "proposed"
    acknowledged = "acknowledged"
    completed = "completed"
    deferred = "deferred"
    help_requested = "help_requested"
    cancelled = "cancelled"


class Action(BaseModel):
    action_id: str = Field(default_factory=new_id)
    report_id: str = ""
    owner_role: OwnerRole = OwnerRole.patient
    action_text: str
    due_at: str | None = None  # RFC3339；无时间依据必须为 null
    due_source: DueSource = DueSource.unknown
    priority: int = 3  # 1 最高
    rationale: str = ""
    source_refs: list[str] = []  # 绑定的 field_id / insight_id / 反馈 ID
    status: ActionStatus = ActionStatus.proposed


class ReportSection(BaseModel):
    key: str
    title_zh: str
    content: str
    claim_ids: list[str] = []


class Report(BaseModel):
    report_id: str = Field(default_factory=new_id)
    case_id: str
    run_id: str
    report_version: int = 1
    status: str = "draft"  # draft|validating|ready|pending_review|rejected|published|superseded|invalidated
    sections: list[ReportSection] = []
    claims: list[ReportClaim] = []
    actions: list[Action] = []
    input_hash: str = ""
    model_id: str = ""
    prompt_version: str = ""
    knowledge_version: str = ""
    policy_version: str = ""
    memory_refs: list[str] = []
    consent_refs: list[dict] = []
    validation: dict = Field(default_factory=dict)  # 校验结果摘要
    created_at: str = ""
