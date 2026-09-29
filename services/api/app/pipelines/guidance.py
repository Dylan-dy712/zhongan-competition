"""温度指引生成（KR3）：六段式个性化报告。

两种执行模式（规格 §5.1 execution_mode 独立记录）：
- live：LLM 生成，输入为"病例事实摘要 + 知识片段 + 痛点 + 用户关注点"，
  输出强制 JSON（六段 + 行动 + 声明），随后做确定性校验；
- mock：无密钥开发联调用的确定性拼装，内容锚定真实病例事实但语言不具
  生成性，演示与盲评必须使用 live 模式。

温度感的实现要点（对应盲评锚点）：承接具体经历（引用本次诊断/手术/天数/
费用结构）、尊重不确定性（待石蜡报告等）、安抚具体不过度保证、行动有
执行者与时间。
"""

from __future__ import annotations

import datetime as _dt

from ..adapters.llm import LLMError
from ..contracts.facts import CaseFacts, ExpenseScope
from ..contracts.guidance import (
    SECTION_KEYS,
    SECTION_ZH,
    Action,
    ClaimType,
    DueSource,
    OwnerRole,
    Report,
    ReportClaim,
    ReportSection,
)
from ..contracts.insights import Insight
from ..knowledge import KNOWLEDGE_VERSION, classify_disease_group

PROMPT_VERSION = "guidance-0.2.0"

SYSTEM_PROMPT = """你是保险公司的理赔后医护关怀专员"暖愈"。基于用户本次理赔的真实医疗记录结构化结果，
为用户写一份个性化康复关怀指引。写作要求：

1. 一切医学事实（诊断、手术、日期、住院天数、药名、金额）只能来自【病例事实】，不得编造或更改数字；
2. 每一段都要承接该用户的具体经历，禁止写成对任意同病种患者都适用的通用科普；
3. 语气温暖、克制、平等：共情要具体（提到 TA 经历过的检查/手术/等待），不过度保证疗效，不替用户断言情绪；
4. 不下诊断、不改处方、不建议停换药；涉及"待病理/待复查"等不确定信息时如实说明并给确认路径；
5. 金额解读只描述结构（总费用、自付、自费、医保支付来自材料），并说明"以结算单为准"；
6. 通俗解释使用知识库提供的说法，不得夸大或引入知识库之外的风险描述；
7. 康复计划与就医建议要可执行：写清楚做什么、找谁、大概什么时候（医嘱有时间就引用，没有就说"以医嘱为准，可在复诊时确认"）。

输出严格 JSON，结构如下（六个 section 全部必填，内容为中文正文，可含换行）：
{
  "sections": {
    "diagnosis_explanation": "...",
    "treatment_review": "...",
    "cost_explanation": "...",
    "recovery_plan": "...",
    "emotional_support": "...",
    "next_visit_advice": "..."
  },
  "actions": [
    {"action_text": "...", "owner_role": "patient|clinician|customer_service",
     "due_at": "RFC3339 或 null", "due_source": "medical_order|user_request|service_policy|unknown",
     "priority": 1-3, "rationale": "..."}
  ],
  "claims": [
    {"text": "报告中的具体事实句", "claim_type": "case_fact|professional_explanation|to_confirm",
     "section": "diagnosis_explanation|..."}
  ]
}
只输出 JSON，不要输出其他内容。"""


def build_facts_digest(facts: CaseFacts, insights: list[Insight], user_context: str = "") -> str:
    enc = facts.encounters[0] if facts.encounters else None

    def yuan(minor: int | None) -> str:
        return f"{(minor or 0) / 100:,.2f} 元" if minor is not None else "材料中未见"

    dx_lines = [f"- {d.name.value}（{'主要' if d.is_primary else '次要'}，{d.role}诊断）" for d in facts.diagnoses if d.name.value]
    proc_lines = [f"- {p.name.value}" + (f"，{p.performed_at.value}" if p.performed_at and p.performed_at.value else "") for p in facts.procedures if p.name.value]
    med_lines = [f"- {m.name.value}" + (f" {m.dosage.value}" if m.dosage and m.dosage.value else "") + (f"，{m.frequency.value}" if m.frequency and m.frequency.value else "") for m in facts.medications if m.name.value]

    total = next((e for e in facts.expenses if e.scope == ExpenseScope.total and e.amount_minor and e.amount_minor.value), None)
    self_paid = next((e for e in facts.expenses if e.scope == ExpenseScope.self_paid and e.amount_minor and e.amount_minor.value), None)
    out_of_catalog = next((e for e in facts.expenses if e.scope == ExpenseScope.out_of_catalog and e.amount_minor and e.amount_minor.value), None)
    ins_paid = next((e for e in facts.expenses if e.scope == ExpenseScope.insurance_paid and e.amount_minor and e.amount_minor.value), None)

    lines = ["【病例事实】(来自理赔材料结构化结果)"]
    if enc is not None:
        if enc.hospital and enc.hospital.value:
            lines.append(f"医院：{enc.hospital.value}")
        if enc.department and enc.department.value:
            lines.append(f"科室：{enc.department.value}")
        if enc.admission_date and enc.admission_date.value:
            lines.append(f"入院：{enc.admission_date.value}")
        if enc.discharge_date and enc.discharge_date.value:
            lines.append(f"出院：{enc.discharge_date.value}")
        if enc.stay_days and enc.stay_days.value:
            lines.append(f"住院天数：{enc.stay_days.value} 天")
    if dx_lines:
        lines.append("诊断：\n" + "\n".join(dx_lines))
    if proc_lines:
        lines.append("手术/操作：\n" + "\n".join(proc_lines))
    if med_lines:
        lines.append("出院带药：\n" + "\n".join(med_lines))
    lines.append(
        "费用（材料口径）："
        f"总费用 {yuan(total.amount_minor.value if total else None)}；"
        f"自付 {yuan(self_paid.amount_minor.value if self_paid else None)}；"
        f"自费/目录外 {yuan(out_of_catalog.amount_minor.value if out_of_catalog else None)}；"
        f"医保统筹支付 {yuan(ins_paid.amount_minor.value if ins_paid else None)}"
    )
    if user_context:
        lines.append(f"【用户自述关注点】{user_context}")
    if insights:
        lines.append("【已识别痛点】")
        for ins in insights:
            if ins.judgment_status.value in ("supported", "candidate"):
                lines.append(f"- [{ins.category.value}] {ins.rationale}")
    return "\n".join(lines)


def _knowledge_block(facts: CaseFacts) -> tuple[str, str | None]:
    g = classify_disease_group(facts)
    if not g:
        return "（未匹配到病种知识包，解释时仅使用通用、无风险表述）", None
    terms = "\n".join(f"- {k}：{v}" for k, v in g["terms"].items())
    rehab = "\n".join(f"- {r}" for r in g["rehab"])
    return (
        f"【病种知识包 {g['zh']}（版本 {KNOWLEDGE_VERSION}）】\n术语通俗解释：\n{terms}\n康复要点：\n{rehab}\n复诊参考：{g['follow_up']}",
        g["code"],
    )


def generate_guidance(facts: CaseFacts, insights: list[Insight], llm, *,
                      user_context: str = "", run_id: str = "", input_hash: str = "") -> Report:
    from ..adapters.llm import MockLLM

    knowledge, group_code = _knowledge_block(facts)

    if isinstance(llm, MockLLM):
        data = _mock_sections_payload(facts, insights, group_code)
        mode = "mock"
    else:
        digest = build_facts_digest(facts, insights, user_context)
        try:
            data = llm.chat_json(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"{digest}\n\n{knowledge}"},
                ],
                max_tokens=4000,
            )
            mode = "live"
        except LLMError:
            data = _mock_sections_payload(facts, insights, group_code)
            mode = "fallback_mock"

    report = _assemble_report(facts, data, insights, run_id=run_id, input_hash=input_hash)
    report.validation["guidance_mode"] = mode
    if mode == "live":
        report.model_id = getattr(llm, "model", "")
    report.prompt_version = PROMPT_VERSION
    report.knowledge_version = KNOWLEDGE_VERSION
    return report


def _mock_sections_payload(facts: CaseFacts, insights: list[Insight], group_code: str | None) -> dict:
    """确定性拼装（mock 模式）：字段锚定真实事实，语言为模板；不得用于盲评/演示。"""
    enc = facts.encounters[0] if facts.encounters else None
    g = next((x for x in _all_groups() if x["code"] == group_code), None)
    dx = next((d.name.value for d in facts.diagnoses if d.is_primary and d.name.value), None) or (
        next((d.name.value for d in facts.diagnoses if d.name.value), None) or "本次诊断"
    )
    proc = "、".join(p.name.value for p in facts.procedures if p.name.value) or None
    stay = enc.stay_days.value if enc is not None and enc.stay_days else None
    total = next((e for e in facts.expenses if e.scope == ExpenseScope.total and e.amount_minor and e.amount_minor.value), None)
    total_y = f"{total.amount_minor.value / 100:,.2f} 元" if total else None
    term_expl = ""
    if g:
        hits = [v for k, v in g["terms"].items() if k in (dx or "") or any(k in (p.name.value or "") for p in facts.procedures)]
        term_expl = "\n".join(f"- {v}" for v in hits[:3])

    def sec(key: str, text: str) -> dict:
        return {"key": key, "text": text}

    return {
        "sections": dict(
            diagnosis_explanation=f"本次出院记录记载的主要诊断是「{dx}」。{term_expl.split(chr(10))[0] if term_expl else ''}".strip(),
            treatment_review=(
                f"本次住院共 {stay or '?'} 天" if stay else "本次就医"
            ) + (f"，接受的手术/操作为：{proc}。" if proc else "材料中未见手术记录。"),
            cost_explanation=(f"材料记载总费用 {total_y}；费用构成与支付方式以医保结算单为准。" if total_y else "材料中未见总费用记载。"),
            recovery_plan="\n".join(g["rehab"]) if g else "请以出院医嘱为准。",
            emotional_support="生病住院是不小的经历，恢复需要时间，请按医嘱休息。",
            next_visit_advice=(g["follow_up"] if g else "请按医嘱复诊。"),
        ),
        "actions": [
            {
                "action_text": "携带出院小结与病理/检查报告复诊" + (f"（{g['follow_up']}" if g else ""),
                "owner_role": "patient", "due_at": None, "due_source": "medical_order", "priority": 1,
                "rationale": "复诊确认恢复进展",
            }
        ],
        "claims": [],
    }


def _all_groups():
    from ..knowledge import GROUPS

    return GROUPS


def _assemble_report(facts: CaseFacts, data: dict, insights: list[Insight], *,
                     run_id: str, input_hash: str) -> Report:
    report = Report(case_id=facts.case_id, run_id=run_id, input_hash=input_hash)
    sections_data = data.get("sections", {})
    claims_by_id: list[ReportClaim] = []
    for c in data.get("claims", [])[:30]:
        try:
            rc = ReportClaim(
                text=str(c.get("text", ""))[:500],
                claim_type=ClaimType(c.get("claim_type", "case_fact")),
                section=c.get("section", ""),
            )
            if rc.text:
                claims_by_id.append(rc)
        except ValueError:
            continue
    for key in SECTION_KEYS:
        content = str(sections_data.get(key, "")).strip()
        if not content:
            content = "（本段内容暂缺：材料中相关信息不足，已在其他段落说明可采取的行动。）"
        report.sections.append(
            ReportSection(key=key, title_zh=SECTION_ZH[key], content=content,
                          claim_ids=[c.claim_id for c in claims_by_id if c.section == key])
        )
    report.claims = claims_by_id

    for a in data.get("actions", [])[:5]:
        try:
            report.actions.append(
                Action(
                    report_id=report.report_id,
                    owner_role=OwnerRole(a.get("owner_role", "patient")),
                    action_text=str(a.get("action_text", ""))[:300],
                    due_at=a.get("due_at"),
                    due_source=DueSource(a.get("due_source", "unknown")),
                    priority=int(a.get("priority", 3)),
                    rationale=str(a.get("rationale", ""))[:300],
                )
            )
        except ValueError:
            continue
    report.actions.sort(key=lambda x: (x.priority, x.due_at is None))
    del report.actions[3:]  # 规格上限：最多三项优先行动

    # 痛点衍生的补充行动（确定性）
    for ins in insights:
        if ins.label_code == "COST_AMOUNT_RECONCILIATION" and ins.judgment_status.value == "candidate":
            report.actions.append(
                Action(report_id=report.report_id, owner_role=OwnerRole.customer_service,
                       action_text="客服协助核对总费用口径差异", due_source=DueSource.service_policy,
                       priority=2, rationale=ins.rationale,
                       source_refs=[ins.insight_id])
            )
    report.created_at = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    return report
