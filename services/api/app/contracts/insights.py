"""痛点识别契约（规格 §6.2）。

六类候选标签目录；category/severity/judgment_status/review_status 四个
维度独立记录，不得混用。正式评测标签须经官方映射确认。
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field

from .common import new_id


class InsightCategory(str, enum.Enum):
    clinical = "clinical"
    cost = "cost"
    experience = "experience"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    undetermined = "undetermined"


class JudgmentStatus(str, enum.Enum):
    candidate = "candidate"
    supported = "supported"
    indeterminate = "indeterminate"
    rejected = "rejected"


class ReviewStatus(str, enum.Enum):
    not_required = "not_required"
    pending = "pending"
    approved = "approved"
    corrected = "corrected"
    rejected = "rejected"


# 候选标签目录（标签代码 -> 中文名称 / 类别 / 默认严重度规则版本）
LABEL_CATALOG: dict[str, dict] = {
    "CLIN_MEDICATION_CONTEXT_REVIEW": {
        "zh": "用药与诊疗情境需核实",
        "category": "clinical",
        "rule_version": "0.1.0",
    },
    "CLIN_EXAM_JUSTIFICATION_REVIEW": {
        "zh": "检查适用性/重复性疑点",
        "category": "clinical",
        "rule_version": "0.1.0",
    },
    "COST_SELF_PAY_DEVIATION": {
        "zh": "自付比例相对可比组偏离",
        "category": "cost",
        "rule_version": "0.1.0",
    },
    "COST_AMOUNT_RECONCILIATION": {
        "zh": "总额与明细/计数待核对",
        "category": "cost",
        "rule_version": "0.1.0",
    },
    "EXP_TERMINOLOGY_BARRIER": {
        "zh": "重要术语缺少通俗说明",
        "category": "experience",
        "rule_version": "0.1.0",
    },
    "EXP_DISCHARGE_GUIDANCE_GAP": {
        "zh": "出院材料指引缺项",
        "category": "experience",
        "rule_version": "0.1.0",
    },
}


class Insight(BaseModel):
    insight_id: str = Field(default_factory=new_id)
    case_id: str = ""
    run_id: str = ""
    label_code: str
    category: InsightCategory
    severity: Severity = Severity.undetermined
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = []
    field_ids: list[str] = []  # 关联事实字段
    rationale: str = ""  # 生成给患者看前需复核改写
    uncertainty: str | None = None
    suggested_action: str = ""
    judgment_status: JudgmentStatus = JudgmentStatus.candidate
    review_required: bool = False
    review_status: ReviewStatus = ReviewStatus.not_required
    rule_version: str = "0.1.0"
    knowledge_refs: list[str] = []
