"""多维痛点识别（KR2）：临床/费用/体验三类、六类候选标签。

分层：本文件是确定性规则层（可复算、可解释），LLM 语义层在其上做
候选补充与理由润色（独立模块）。规则层输出 judgment_status，
不得把"疑点"升级为"确定的医疗不当"（规格 §6.2）。
"""

from __future__ import annotations

from ..contracts.facts import CaseFacts, ExpenseScope
from ..contracts.insights import (
    Insight,
    InsightCategory,
    JudgmentStatus,
    ReviewStatus,
    Severity,
)

# 药物-适应证简表（候选知识包 v0.1，正式版需获准知识库替换）
_DRUG_INDICATION_HINTS = [
    (r"头孢|阿莫西林|左氧氟沙星|莫西沙星|阿奇霉素|哌拉西林", ["感染", "肺炎", "支气管", "炎症", "脓", "术后"]),
    (r"氨溴索|乙酰半胱氨酸", ["肺炎", "支气管", "咳嗽", "痰", "术后"]),
    (r"奥美拉唑|泮托拉唑|埃索美拉唑", ["溃疡", "胃炎", "胃", "反流", "应激"]),
    (r"二甲双胍|格列|胰岛素|达格列净", ["糖尿病", "血糖"]),
    (r"阿托伐他汀|瑞舒伐他汀", ["冠心", "血脂", "动脉", "心梗"]),
    (r"氯吡格雷|阿司匹林", ["冠心", "支架", "心梗", "脑梗", "血栓"]),
    (r"钙片|骨化三醇|维生素D", ["骨", "骨折", "疏松"]),
    (r"布洛芬|塞来昔布|洛索洛芬", ["痛", "骨折", "术"]),
    (r"低分子肝素|那屈肝素|依诺肝素", ["血栓", "术", "卧床", "制動", "制动"]),
]

# 高频重复检查关注名单（名称片段 -> 关注阈值次数）
_REPEAT_EXAM_WATCH = [
    (r"CT|计算机断层", 3),
    (r"磁共振|MR[I]?", 2),
    (r"彩超|多普勒|超声", 4),
    (r"心电图", 4),
    (r"胸片|X线|DR", 3),
]

# 出院材料指引适用清单（规格 §6.2：相对适用清单的缺项，不断言医生未口头指导）
_DISCHARGE_GUIDANCE_ITEMS = [
    ("复诊安排", r"复诊|随访|门诊复查|定期复查"),
    ("用药指导", r"出院带药|口服|用药|服药"),
    ("康复/活动指导", r"康复|功能锻炼|活动|休息|避免"),
    ("病情观察/预警", r"如有|不适|及时|异常|症状加重"),
]

# 面向患者的通俗词表（用于术语晦涩标签的"已有通俗解释"判断）
_PLAIN_EXPLAINED_MARKERS = r"通俗|意思是|俗称|即|简单来说"


def detect_insights(facts: CaseFacts, bundle: dict | None = None,
                    cohort_stats: dict | None = None) -> list[Insight]:
    case_id = facts.case_id
    out: list[Insight] = []
    pages = (bundle or {}).get("pages", [])
    full_text = "\n".join(p.get("text", "") for p in pages)

    out.extend(_medication_context_review(facts, case_id, full_text))
    out.extend(_exam_justification_review(facts, case_id, full_text))
    out.extend(_self_pay_deviation(facts, case_id, cohort_stats))
    out.extend(_amount_reconciliation(facts, case_id))
    out.extend(_terminology_barrier(facts, case_id))
    out.extend(_discharge_guidance_gap(facts, case_id, full_text))
    return out


# ---------- clinical ----------


def _medication_context_review(facts: CaseFacts, case_id: str, full_text: str) -> list[Insight]:
    import re

    dx_text = "；".join(d.name.value or "" for d in facts.diagnoses if d.name.value)
    hits: list[Insight] = []
    for med in facts.medications:
        name = med.name.value or ""
        matched_hint = None
        for rx, indications in _DRUG_INDICATION_HINTS:
            if re.search(rx, name):
                matched_hint = indications
                break
        if matched_hint is None:
            continue
        if not any(k in dx_text for k in matched_hint):
            ev = med.name.evidence_ids[:1]
            hits.append(
                Insight(
                    case_id=case_id, label_code="CLIN_MEDICATION_CONTEXT_REVIEW",
                    category=InsightCategory.clinical, severity=Severity.low,
                    confidence=0.5, evidence_ids=ev, field_ids=[med.name.field_id],
                    rationale=f"「{name}」的常见适应证与本次记录的诊断之间未见直接对应，可能存在资料未覆盖的用药原因（如预防性用药）。",
                    uncertainty="仅基于候选知识表；缺少完整医嘱与检验证据时不可判定用药是否恰当",
                    suggested_action="如需确认，可在复诊时向医生核实该药与本次病情的关系。",
                    judgment_status=JudgmentStatus.indeterminate,
                    review_required=True, review_status=ReviewStatus.pending,
                )
            )
    return hits[:5]


def _exam_justification_review(facts: CaseFacts, case_id: str, full_text: str) -> list[Insight]:
    import re

    hits: list[Insight] = []
    lines = full_text.splitlines()
    for rx, threshold in _REPEAT_EXAM_WATCH:
        n = sum(1 for ln in lines if re.search(rx, ln))
        if n >= threshold:
            # 找一条证据行
            ev_line = next((i for i, ln in enumerate(lines) if re.search(rx, ln)), None)
            hits.append(
                Insight(
                    case_id=case_id, label_code="CLIN_EXAM_JUSTIFICATION_REVIEW",
                    category=InsightCategory.clinical, severity=Severity.low,
                    confidence=0.45, evidence_ids=[],
                    rationale=f"材料中{rx.replace('|', '/')}相关记录出现约 {n} 次，超过常规复查频次参考值 {threshold}，可能是病情监测需要，也可能存在重复检查。",
                    uncertainty="OCR 行计数含报告单标题与页眉；术后/住院期间多次检查可能完全合理",
                    suggested_action="如对检查必要性有疑问，可携带清单请医生说明各项检查的目的。",
                    judgment_status=JudgmentStatus.indeterminate,
                    review_required=True, review_status=ReviewStatus.pending,
                )
            )
            break
    return hits


# ---------- cost ----------


def _self_pay_deviation(facts: CaseFacts, case_id: str, cohort_stats: dict | None) -> list[Insight]:
    total = next((e for e in facts.expenses if e.scope == ExpenseScope.total and e.amount_minor and e.amount_minor.value), None)
    self_paid = next((e for e in facts.expenses if e.scope == ExpenseScope.self_paid and e.amount_minor and e.amount_minor.value), None)
    if not total or not self_paid:
        return []
    ratio = self_paid.amount_minor.value / total.amount_minor.value
    ref = (cohort_stats or {}).get("self_pay_ratio_median")
    if ref is None:
        return [
            Insight(
                case_id=case_id, label_code="COST_SELF_PAY_DEVIATION",
                category=InsightCategory.cost, severity=Severity.undetermined,
                confidence=None, evidence_ids=(self_paid.amount_minor.evidence_ids or [])[:1],
                field_ids=[self_paid.amount_minor.field_id, total.amount_minor.field_id],
                rationale=f"本次自付占比约 {ratio:.0%}。缺少可比病种基准，暂无法判断是否偏离常态。",
                uncertainty="无可比基准时不可判定异常（规格 §6.2）",
                suggested_action="可在理赔详情中查看费用构成明细。",
                judgment_status=JudgmentStatus.indeterminate,
                review_required=False,
            )
        ]
    if ratio - ref > 0.15:
        return [
            Insight(
                case_id=case_id, label_code="COST_SELF_PAY_DEVIATION",
                category=InsightCategory.cost, severity=Severity.medium,
                confidence=0.6, evidence_ids=(self_paid.amount_minor.evidence_ids or [])[:1],
                field_ids=[self_paid.amount_minor.field_id],
                rationale=f"自付占比约 {ratio:.0%}，高于可比病例组中位数（{ref:.0%}），可能与自费项目占比有关。",
                uncertainty="基准来自历史脱敏统计，受病种/术式构成影响",
                suggested_action="查看费用清单中的自费项目明细，了解主要来源。",
                judgment_status=JudgmentStatus.candidate,
                review_required=False,
            )
        ]
    return []


def _amount_reconciliation(facts: CaseFacts, case_id: str) -> list[Insight]:
    totals = [e for e in facts.expenses if e.scope == ExpenseScope.total and e.amount_minor and e.amount_minor.value is not None]
    if len(totals) < 2:
        return []
    vals = {t.amount_minor.value for t in totals}
    if len(vals) == 1:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo <= 100:  # 1 元以内视作口径四舍五入
        return []
    doc_ids = ",".join(sorted({t.document_id for t in totals}))
    return [
        Insight(
            case_id=case_id, label_code="COST_AMOUNT_RECONCILIATION",
            category=InsightCategory.cost, severity=Severity.medium,
            confidence=0.75, evidence_ids=[ev for t in totals for ev in (t.amount_minor.evidence_ids or [])][:2],
            rationale=f"不同材料记录的总费用不一致（相差 {(hi-lo)/100:.2f} 元），需核对口径。",
            uncertainty="可能来自门诊+住院合并口径、补记项目或结算时点差异",
            suggested_action="以医保结算单为准核对；如金额影响理赔，请联系客服协助核对。",
            judgment_status=JudgmentStatus.candidate,
            review_required=False,
        )
    ]


# ---------- experience ----------


def _terminology_barrier(facts: CaseFacts, case_id: str) -> list[Insight]:
    import re

    jargon_pat = re.compile(
        r"(VATS|胸腔镜|腹腔镜|磨玻璃|亚实性|占位|结节|萎缩|反流|不全|功能障碍|突出|狭窄|"
        r"腺上皮增生|分化|浸润|粘连|坏死|囊肿|息肉|糜烂|溃疡|结石|脱垂|疝|瘘|"
        r"慢性|急性|良性|恶性|待排|待石蜡)"
    )
    terms: dict[str, int] = {}
    for d in facts.diagnoses:
        for t in jargon_pat.findall(d.name.value or ""):
            terms[t] = terms.get(t, 0) + 1
    for p in facts.procedures:
        for t in jargon_pat.findall(p.name.value or ""):
            terms[t] = terms.get(t, 0) + 1
    if not terms:
        return []
    top = sorted(terms.items(), key=lambda kv: -kv[1])[:6]
    term_list = "、".join(t for t, _ in top)
    ev_ids = [e for d in facts.diagnoses for e in (d.name.evidence_ids or [])][:1]
    return [
        Insight(
            case_id=case_id, label_code="EXP_TERMINOLOGY_BARRIER",
            category=InsightCategory.experience, severity=Severity.low,
            confidence=0.8, evidence_ids=ev_ids,
            rationale=f"本次诊断与手术记录中包含较多专业术语（{term_list}），需要通俗解释。",
            uncertainty=None,
            suggested_action="在关怀报告中已附通俗解释；仍有疑问可咨询客服或复诊时询问。",
            judgment_status=JudgmentStatus.supported,
            review_required=False,
        )
    ]


def _discharge_guidance_gap(facts: CaseFacts, case_id: str, full_text: str) -> list[Insight]:
    import re

    has_discharge_doc = bool(facts.diagnoses) and bool(facts.encounters and facts.encounters[0].discharge_date)
    if not has_discharge_doc:
        return []
    missing = [name for name, pat in _DISCHARGE_GUIDANCE_ITEMS if not re.search(pat, full_text)]
    if not missing:
        return []
    sev = Severity.low if len(missing) <= 1 else Severity.medium
    return [
        Insight(
            case_id=case_id, label_code="EXP_DISCHARGE_GUIDANCE_GAP",
            category=InsightCategory.experience, severity=sev,
            confidence=0.7, evidence_ids=[],
            rationale=f"所提供的出院材料中，以下指引项目未见书面记载：{'、'.join(missing)}。",
            uncertainty="仅指书面材料缺项，不代表医生未作口头指导（规格 §6.2）",
            suggested_action="关怀报告已按常规康复要点补充建议；具体请以医生意见为准。",
            judgment_status=JudgmentStatus.supported,
            review_required=False,
        )
    ]
