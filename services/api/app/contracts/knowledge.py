"""Medical knowledge entry contract — versioned knowledge packs (spec.md 4.2, T19).

Source of truth: docs/medical/knowledge/**.md (drafts) compiled into
contracts/knowledge/entries.jsonl by tools/build_knowledge_jsonl.py.
Entries are NOT patient-visible content until status is approved and the
knowledge manifest records the reviewer.
"""

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .core import Contract


class DiseaseCode(str, Enum):
    fx = "FX"  # 骨折
    fy = "FY"  # 肺炎（社区获得性）
    gx = "GX"  # 冠心病
    yz = "YZ"  # 腰椎间盘突出症
    tn = "TN"  # 2型糖尿病
    hj = "HJ"  # 成人股骨头坏死与髋关节置换的一般解释
    ty = "TY"  # 通用（跨病种）


class KnowledgeStatus(str, Enum):
    draft = "draft-待医学审核"
    approved = "approved"


class KnowledgeEntry(Contract):
    """One machine-readable knowledge entry compiled from a pack slot file."""

    entry_id: str = Field(
        pattern=r"^(FX|FY|GX|YZ|TN|HJ)-S\d{1,2}-\d{2}$|^TY-COST-\d{2}$",
        description="稳定引用 ID，如 FX-S4-01 / TY-COST-03；knowledge_refs 的定位依据",
    )
    pack_id: str = Field(pattern=r"^KP-(FX|FY|GX|YZ|TN|HJ|TY)$")
    disease_code: DiseaseCode
    slot: str = Field(
        pattern=r"^S\d{1,2}$|^TY$",
        description="知识槽位 S1-S11；TY 为通用单文件",
    )
    slot_file: str = Field(description="来源槽位文件名（相对包目录），供证据回溯")
    title: str | None = Field(default=None, max_length=80)
    applicable_scope: str | None = None
    content: str = Field(min_length=1)
    anchoring: str | None = Field(
        default=None,
        description="使用前必须结合的病例事实（QG-03 个性化验收的绑定依据）",
    )
    purposes: list[str] = Field(default_factory=list)
    source: str | None = None
    status: KnowledgeStatus = KnowledgeStatus.draft
    reviewed_by: str | None = Field(
        default=None, description="医学审核人；仅 approved 条目允许填写"
    )
    reviewed_at: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="医学审核日期，YYYY-MM-DD；仅 approved 条目允许填写",
    )
    status_note: str | None = Field(
        default=None, description="状态附注，如查证修订记录"
    )
    numeric_pending_review: bool = Field(
        default=False,
        description="content 含【数值待医学审核】——未获准前装配器必须阻断注入患者可见内容",
    )
    platform_verified: bool = Field(
        default=False,
        description="status_note 标注经氢离子平台查证（辅助核对线索，非医学审核）",
    )
    ai_verified: bool = Field(
        default=False,
        description="是否完成专业医疗智能体核验；不等同于真人医学审核批准",
    )
    ai_verification_source: str | None = None
    origin_format: Literal["list", "table"] = "list"

    @model_validator(mode="after")
    def approved_entries_require_review_metadata(self) -> "KnowledgeEntry":
        if self.status == KnowledgeStatus.approved and not (
            self.reviewed_by and self.reviewed_at
        ):
            raise ValueError("approved knowledge requires reviewed_by and reviewed_at")
        if self.status == KnowledgeStatus.draft and (
            self.reviewed_by or self.reviewed_at
        ):
            raise ValueError("draft knowledge cannot carry approval metadata")
        if self.ai_verified and not self.ai_verification_source:
            raise ValueError("ai_verified knowledge requires ai_verification_source")
        return self


class KnowledgePackMeta(Contract):
    pack_id: str
    disease_code: DiseaseCode
    version: str
    status: KnowledgeStatus
    scope: str | None = None
    exclusions: str | None = None
    entries_total: int
    slot_counts: dict[str, int]


class KnowledgeBuildReport(Contract):
    built_at: str
    packs: list[KnowledgePackMeta]
    entries_total: int
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_errors: list[str] = Field(default_factory=list)
