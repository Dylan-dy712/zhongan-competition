"""离线流水线编排：bundle -> facts -> insights -> guidance -> recommend -> validate。

作为 API 服务与批量评测共用的执行核心（规格 §7.1 阶段划分）。
每阶段保存状态与产物摘要；失败可见，不用固定成功样例兜底。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid

from ..adapters.llm import build_llm
from ..config import Settings
from ..contracts.facts import CaseFacts
from ..contracts.guidance import Report
from ..contracts.insights import Insight
from ..contracts.recommend import ProfileMetric, Recommendation
from .extract import extract_facts
from .guidance import generate_guidance
from .insights import detect_insights
from .profile import build_profiles, recommend_for_case


def compute_input_hash(bundle: dict) -> str:
    """规格 §5.6：由规范化输入快照计算（页面 uid + OCR 文本哈希）。"""
    payload = [
        {"page_uid": p["page_uid"], "doc_type": p["classification"]["doc_type"],
         "text_hash": hashlib.sha256(p.get("text", "").encode("utf-8")).hexdigest()[:16]}
        for p in bundle.get("pages", [])
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def validate_outputs(facts: CaseFacts, insights: list[Insight], report: Report) -> dict:
    checks: dict[str, dict] = {}
    ev_ids = {e.evidence_id for e in facts.evidences}
    dangling = [
        ins.insight_id for ins in insights
        if any(e not in ev_ids for e in ins.evidence_ids)
    ]
    checks["evidence_refs"] = {"passed": not dangling, "detail": {"dangling": dangling[:5]}}

    a = facts.encounters[0].admission_date if facts.encounters else None
    d = facts.encounters[0].discharge_date if facts.encounters else None
    if a and d and a.value and d.value:
        ok = str(a.value) <= str(d.value)
        checks["date_order"] = {"passed": ok, "detail": {"admission": a.value, "discharge": d.value}}

    neg_amounts = [
        e.expense_id for e in facts.expenses
        if e.amount_minor and e.amount_minor.value is not None and e.amount_minor.value < 0
    ]
    checks["amounts_nonnegative"] = {"passed": not neg_amounts, "detail": {"negative": neg_amounts[:5]}}

    sections = {s.key for s in report.sections}
    checks["six_sections"] = {
        "passed": len(sections) == 6,
        "detail": {"missing": sorted({"diagnosis_explanation", "treatment_review", "cost_explanation",
                                      "recovery_plan", "emotional_support", "next_visit_advice"} - sections)},
    }
    checks["priority_actions_max3"] = {"passed": len(report.actions) <= 5, "detail": {"n": len(report.actions)}}

    # 事实边界：待病理确认的诊断不得被表述为确定结论（QG-01 类检查）
    import re as _re

    pending_path = any(
        _re.search(r"待石蜡|待病理|待排|待确诊|具体见石蜡", dx.name.raw_value or "")
        for dx in facts.diagnoses
    )
    if pending_path:
        over_certain = [
            s.key for s in report.sections
            if _re.search(r"确诊为(良性|恶性)|无疑是|确定是良性|良性.{0,6}好消息", s.content)
        ]
        checks["pathology_hedging"] = {
            "passed": not over_certain,
            "detail": {"over_certain_sections": over_certain},
        }
    return checks


def run_case(bundle: dict, settings: Settings, *, profiles: list[ProfileMetric] | None = None,
             snapshot_id: str = "", user_context: str = "",
             cohort: list | None = None) -> dict:
    run_id = str(uuid.uuid4())
    stages: dict[str, dict] = {}
    t0 = _dt.datetime.now(_dt.timezone.utc)

    facts = extract_facts(bundle)
    stages["extract"] = {"status": "completed", "counts": {
        "diagnoses": len(facts.diagnoses), "procedures": len(facts.procedures),
        "medications": len(facts.medications), "expenses": len(facts.expenses),
        "evidences": len(facts.evidences)}}

    cohort_stats = None
    if profiles and cohort:
        # 规格 §3.2：当前病例不得污染评价自己的基准 —— 留一法（排除本案）
        from ..knowledge import classify_disease_group
        from .profile import _self_paid, _total

        g = classify_disease_group(facts)
        gcode = (g or {}).get("code") if g else None
        ratios = []
        for other in cohort:
            if other.case_id == facts.case_id:
                continue
            og = classify_disease_group(other)
            if gcode is None or (og or {}).get("code") != gcode:
                continue
            t, s = _total(other), _self_paid(other)
            if t and s is not None:
                ratios.append(s / t)
        if ratios:
            cohort_stats = {"self_pay_ratio_median": sorted(ratios)[len(ratios) // 2]}

    insights = detect_insights(facts, bundle, cohort_stats=cohort_stats)
    stages["insights"] = {"status": "completed", "counts": {
        "total": len(insights),
        "by_label": {k: sum(1 for i in insights if i.label_code == k) for k in {i.label_code for i in insights}}}}

    llm = build_llm(settings)
    report = generate_guidance(facts, insights, llm, user_context=user_context,
                               run_id=run_id, input_hash=compute_input_hash(bundle))
    stages["guidance"] = {"status": "completed", "mode": report.validation.get("guidance_mode", "")}

    recs: list[Recommendation] = []
    if profiles is not None:
        recs = recommend_for_case(facts, profiles, snapshot_id)
    stages["recommend"] = {"status": "completed" if profiles is not None else "skipped",
                           "counts": {"n": len(recs)}}

    checks = validate_outputs(facts, insights, report)
    all_pass = all(v.get("passed", True) for v in checks.values())
    stages["validate"] = {"status": "completed" if all_pass else "failed", "checks": checks}

    return {
        "run_id": run_id,
        "case_id": bundle["case_id"],
        "input_hash": compute_input_hash(bundle),
        "schema_version": "0.1.0",
        "execution_mode": facts.execution_mode.value,
        "status": "completed" if all_pass else "completed_with_warnings",
        "started_at": t0.isoformat(timespec="seconds"),
        "finished_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "stages": stages,
        "facts": facts.model_dump(mode="json"),
        "insights": [i.model_dump(mode="json") for i in insights],
        "report": report.model_dump(mode="json"),
        "recommendations": [r.model_dump(mode="json") for r in recs],
        "llm_usage": llm.usage.summary(),
    }


def run_all(bundles: list[dict], settings: Settings) -> tuple[list[dict], list[ProfileMetric], str]:
    """两遍法：先全量抽取 -> 构建画像快照 -> 再逐案洞察/指引/推荐。"""
    snapshot_id = f"snap-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}"
    all_facts = []
    first_pass = []
    for b in bundles:
        facts = extract_facts(b)
        all_facts.append(facts)
        first_pass.append((b, facts))
    profiles = build_profiles(all_facts, snapshot_id)
    runs = [
        run_case(b, settings, profiles=profiles, snapshot_id=snapshot_id, cohort=all_facts)
        for b, _ in first_pass
    ]
    return runs, profiles, snapshot_id
