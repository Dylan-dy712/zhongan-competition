"""品质画像与可解释推荐契约（规格 §6.5）。"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field

from .common import new_id


class EntityType(str, enum.Enum):
    hospital = "hospital"
    doctor = "doctor"
    treatment_plan = "treatment_plan"


class ProfileMetric(BaseModel):
    """画像指标：分子/分母可复算；不可计算不得写 0。"""

    entity_id: str
    entity_type: EntityType
    entity_name: str = ""
    disease_group: str = ""
    metric_name: str
    numerator: float | None = None
    denominator: float | None = None
    value: float | None = None
    unit: str = ""
    window_start: str = ""
    window_end: str = ""
    sample_count: int = 0
    missing_rate: float | None = None
    computable: bool = False
    limitations: list[str] = []
    snapshot_id: str = ""
    metric_version: str = "0.1.0"
    comparison_group_id: str | None = None


class MatchReason(BaseModel):
    reason_code: str
    text: str  # 面向患者的话术，引用指标
    metric_refs: list[str] = []  # ProfileMetric 标识（snapshot_id+entity+metric）
    need_refs: list[str] = []  # 用户明确需求/病例事实引用


class Recommendation(BaseModel):
    candidate_id: str = Field(default_factory=new_id)
    entity_id: str
    entity_type: EntityType
    entity_name: str = ""
    eligible: bool = True
    match_reasons: list[MatchReason] = []
    limitations: list[str] = []
    metric_snapshot_refs: list[str] = []
    ranking_allowed: bool = False
    rank: int | None = None
    rejection_reason: str | None = None
    policy_version: str = "0.1.0"
