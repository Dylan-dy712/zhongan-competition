"""品质画像与可解释推荐（KR4）。

数据来源：全部案件的结构化事实（离线批量聚合），输出不可变快照。
指标可复算（保存分子/分母与样本数），不可计算不得补零；
推荐理由必须引用快照指标，禁止 LLM 自由发挥口碑（规格 §6.5）。
"""

from __future__ import annotations

from ..contracts.facts import CaseFacts, ExpenseScope
from ..contracts.recommend import EntityType, MatchReason, ProfileMetric, Recommendation
from ..knowledge import classify_disease_group

METRIC_VERSION = "0.1.0"
POLICY_VERSION = "profile-policy-0.1.0"
MIN_SAMPLE = 5  # 样本门槛：低于此值不排序


def _total(f: CaseFacts) -> int | None:
    e = next((x for x in f.expenses if x.scope == ExpenseScope.total and x.amount_minor and x.amount_minor.value is not None), None)
    return e.amount_minor.value if e else None


def _self_paid(f: CaseFacts) -> int | None:
    e = next((x for x in f.expenses if x.scope == ExpenseScope.self_paid and x.amount_minor and x.amount_minor.value is not None), None)
    return e.amount_minor.value if e else None


def _stay(f: CaseFacts) -> int | None:
    enc = f.encounters[0] if f.encounters else None
    if enc is not None and enc.stay_days and enc.stay_days.value is not None:
        return enc.stay_days.value
    return None


def build_profiles(all_facts: list[CaseFacts], snapshot_id: str) -> list[ProfileMetric]:
    """按 医院 × 病种组 聚合五类指标（费用水平/自付负担/住院天数/用药记录/指引完整度）。"""
    groups: dict[tuple[str, str], list[CaseFacts]] = {}
    for f in all_facts:
        enc = f.encounters[0] if f.encounters else None
        if enc is None or not enc.hospital or not enc.hospital.value:
            continue
        g = classify_disease_group(f)
        gcode = (g or {}).get("code", "unmatched")
        groups.setdefault((enc.hospital.value, gcode), []).append(f)

    metrics: list[ProfileMetric] = []
    for (hospital, gcode), cases in sorted(groups.items()):
        n = len(cases)
        totals = [t for t in (_total(f) for f in cases) if t is not None]
        selfpaids = [s for s in (_self_paid(f) for f in cases) if s is not None]
        stays = [s for s in (_stay(f) for f in cases) if s is not None]
        with_med = sum(1 for f in cases if f.medications)
        with_discharge_guidance = sum(
            1 for f in cases
            if f.completeness.diagnoses == "found" and f.encounters and f.encounters[0].discharge_date
        )

        def med(metric_name: str, value, unit: str, numerator=None, denominator=None,
                limitations=None) -> ProfileMetric:
            return ProfileMetric(
                entity_id=hospital, entity_type=EntityType.hospital, entity_name=hospital,
                disease_group=gcode, metric_name=metric_name,
                numerator=numerator, denominator=denominator,
                value=value, unit=unit, sample_count=n,
                computable=value is not None, limitations=limitations or [],
                snapshot_id=snapshot_id, metric_version=METRIC_VERSION,
            )

        if totals:
            totals_sorted = sorted(totals)
            mid = totals_sorted[len(totals_sorted) // 2]
            metrics.append(med("total_cost_median", mid / 100, "CNY",
                               limitations=[f"样本 {len(totals)}/{n} 有总费用记录"]))
        else:
            metrics.append(med("total_cost_median", None, "CNY",
                               limitations=["无总费用记录，不可计算"]))
        if selfpaids and totals:
            sp = sum(selfpaids)
            tp = sum(totals)
            metrics.append(med("self_pay_ratio", round(sp / tp, 4), "ratio", sp, tp,
                               limitations=[f"自付口径为医院结算自付，非商保赔付后净负担"]))
        else:
            metrics.append(med("self_pay_ratio", None, "ratio", None, n,
                               limitations=["缺少自付或总费用记录，不可计算"]))
        if stays:
            stays_sorted = sorted(stays)
            metrics.append(med("stay_days_median", stays_sorted[len(stays_sorted) // 2], "天",
                               limitations=[f"样本 {len(stays)}/{n}"]))
        else:
            metrics.append(med("stay_days_median", None, "天", None, n,
                               limitations=["无住院天数记录"]))
        metrics.append(med("medication_documented_ratio", round(with_med / n, 4), "ratio", with_med, n,
                           limitations=["文档代理指标：仅说明出院带药被书面记录的比例"]))
        metrics.append(med("discharge_doc_completeness", round(with_discharge_guidance / n, 4), "ratio",
                           with_discharge_guidance, n,
                           limitations=["文档代理指标：有出院诊断+出院日期记录的比例，不代表疗效"]))
    return metrics


def recommend_for_case(facts: CaseFacts, metrics: list[ProfileMetric], snapshot_id: str,
                       top_k: int = 3) -> list[Recommendation]:
    """同类病种下给出可解释的机构推荐；不足门槛时 ranking_allowed=False。"""
    g = classify_disease_group(facts)
    gcode = (g or {}).get("code") if g else None
    if not gcode:
        return []
    cur_hospital = None
    enc = facts.encounters[0] if facts.encounters else None
    if enc is not None and enc.hospital and enc.hospital.value:
        cur_hospital = enc.hospital.value

    # 同病种组的医院指标
    by_hospital: dict[str, dict[str, ProfileMetric]] = {}
    for m in metrics:
        if m.disease_group == gcode and m.entity_type == EntityType.hospital:
            by_hospital.setdefault(m.entity_id, {})[m.metric_name] = m

    cohort_costs = sorted(
        m.value for hs in by_hospital.values() for m in hs.values()
        if m.metric_name == "total_cost_median" and m.value is not None
    )
    cohort_mid = cohort_costs[len(cohort_costs) // 2] if cohort_costs else None

    recs: list[Recommendation] = []
    for hid, ms in by_hospital.items():
        n = max((m.sample_count for m in ms.values()), default=0)
        reasons: list[MatchReason] = []
        limitations: list[str] = []
        cost = ms.get("total_cost_median")
        sp = ms.get("self_pay_ratio")
        stay = ms.get("stay_days_median")
        doc = ms.get("discharge_doc_completeness")

        eligible = cost is not None and n >= MIN_SAMPLE
        if not eligible:
            limitations.append(f"样本量 {n} 低于排序门槛 {MIN_SAMPLE}，仅展示描述性信息")

        if cost is not None and cohort_mid:
            rel = "低于" if cost < cohort_mid else ("接近" if abs(cost - cohort_mid) / cohort_mid < 0.15 else "高于")
            reasons.append(MatchReason(
                reason_code="cost_level_vs_cohort",
                text=f"该院同病种历史总费用中位数约 {cost:,.0f} 元，{rel}同类机构中位数（{cohort_mid:,.0f} 元）",
                metric_refs=[f"{snapshot_id}:{hid}:total_cost_median"],
            ))
        if sp is not None and sp.computable:
            reasons.append(MatchReason(
                reason_code="self_pay_ratio",
                text=f"历史同类病例自付占比约 {sp.value:.0%}（医院结算口径，医保待遇不同会有差异）",
                metric_refs=[f"{snapshot_id}:{hid}:self_pay_ratio"],
            ))
        if stay is not None and stay.computable:
            reasons.append(MatchReason(
                reason_code="stay_days",
                text=f"同病种平均住院时长中位数约 {stay.value} 天",
                metric_refs=[f"{snapshot_id}:{hid}:stay_days_median"],
            ))
        if doc is not None and doc.computable:
            reasons.append(MatchReason(
                reason_code="discharge_doc",
                text=f"出院材料完整度记录比例约 {doc.value:.0%}（文档代理指标，仅供参考）",
                metric_refs=[f"{snapshot_id}:{hid}:discharge_doc_completeness"],
            ))

        rec = Recommendation(
            entity_id=hid, entity_type=EntityType.hospital, entity_name=hid,
            eligible=eligible,
            match_reasons=reasons[:4],
            limitations=limitations,
            metric_snapshot_refs=[f"{snapshot_id}:{hid}:{k}" for k in ms],
            ranking_allowed=eligible and len(reasons) >= 2,
            policy_version=POLICY_VERSION,
        )
        if hid == cur_hospital:
            rec.limitations.append("本次就医机构")
        recs.append(rec)

    # 排序：可排序的在前，费用水平相对低优先
    rankable = [r for r in recs if r.ranking_allowed]
    others = [r for r in recs if not r.ranking_allowed]
    rankable.sort(key=lambda r: next(
        (m.value for m in metrics if m.entity_id == r.entity_id and m.metric_name == "total_cost_median"), 9e9
    ))
    for i, r in enumerate(rankable):
        r.rank = i + 1
    return rankable[:top_k] + others[: max(0, top_k - len(rankable))]
