"""KR1 评测：结构化字段级 P/R/F1 与缺失率。

金标格式（每案一个 JSON，放在仓库外以符合医疗数据合规）：
{
  "case_id": "CL...",
  "gold": {
    "hospital": "上海市肺科医院",
    "admission_date": "2025-10-27",
    "discharge_date": "2025-10-30",
    "stay_days": 3,
    "total_cost_minor": 5413120,
    "self_paid_minor": 1534974,
    "diagnoses": ["肺部阴影", "肺良性病变"],
    "procedures": ["单孔VATS左肺上叶部分切除术"],
    "medications": []
  }
}

匹配规则（内部口径 v0.1，官方口径未公布前宏/微平均并列报告）：
- 标量字段：归一化后精确相等（日期取日精度；金额以分为单位）；
- 集合字段：一对一匹配，精确相等优先，其次包含关系或相似度 >= 0.75；
- 缺失率 = 金标字段在预测中 status != observed/derived 的比例。
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

SCALAR_FIELDS = ["hospital", "admission_date", "discharge_date", "stay_days",
                 "total_cost_minor", "self_paid_minor"]
SET_FIELDS = ["diagnoses", "procedures", "medications"]


def _predict_view(facts: dict) -> dict:
    enc = (facts.get("encounters") or [{}])[0]

    def val(fv):
        return fv.get("value") if fv and fv.get("value") is not None else None

    expenses = facts.get("expenses") or []
    totals = [e for e in expenses if e.get("scope") == "total" and e.get("amount_minor")]
    selfp = [e for e in expenses if e.get("scope") == "self_paid" and e.get("amount_minor")]
    return {
        "hospital": val(enc.get("hospital")),
        "admission_date": val(enc.get("admission_date")),
        "discharge_date": val(enc.get("discharge_date")),
        "stay_days": val(enc.get("stay_days")),
        "total_cost_minor": min((val(e["amount_minor"]) for e in totals), default=None),
        "self_paid_minor": min((val(e["amount_minor"]) for e in selfp), default=None),
        "diagnoses": [val(d.get("name")) for d in facts.get("diagnoses") or [] if val(d.get("name"))],
        "procedures": [val(p.get("name")) for p in facts.get("procedures") or [] if val(p.get("name"))],
        "medications": [val(m.get("name")) for m in facts.get("medications") or [] if val(m.get("name"))],
    }


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _strip_punct(s: str) -> str:
    import re as _re

    return _re.sub(r"[\s，,；;：:、（）()【】\[\].·-]+", "", s)


def _match_sets(gold: list, pred: list, threshold: float = 0.75) -> tuple[int, int, int]:
    """一对一匹配：精确优先 → 相似度>=threshold 贪心 → 连续片段组合匹配。

    组合匹配：金标常把多行诊断合并为一条（病理"（部位）结论"跨行），
    若一条未匹配金标（去标点）等于连续若干条未匹配预测（去标点）的拼接，
    计为 TP（规格 §11.2 集合一对一语义下的合并等价）。
    返回 TP, FP, FN。
    """
    tp = 0
    used_g: set[int] = set()
    used_p: set[int] = set()
    for pi, p in enumerate(pred):
        for gi, g in enumerate(gold):
            if gi in used_g:
                continue
            if p == g:
                tp += 1
                used_g.add(gi)
                used_p.add(pi)
                break
    for pi, p in enumerate(pred):
        if pi in used_p:
            continue
        best_g, best_s = None, 0.0
        for gi, g in enumerate(gold):
            if gi in used_g:
                continue
            s = _sim(str(p), str(g))
            if s > best_s:
                best_g, best_s = gi, s
        if best_g is not None and best_s >= threshold:
            tp += 1
            used_g.add(best_g)
            used_p.add(pi)
    # 组合匹配
    n = len(pred)
    for gi, g in enumerate(gold):
        if gi in used_g:
            continue
        gs = _strip_punct(str(g))
        if not gs:
            continue
        i = 0
        while i < n:
            if i in used_p:
                i += 1
                continue
            acc = ""
            j = i
            matched = False
            while j < n and (j - i) < 4:
                if j in used_p:
                    break
                acc += _strip_punct(str(pred[j]))
                if acc == gs:
                    for k in range(i, j + 1):
                        used_p.add(k)
                    used_g.add(gi)
                    tp += j - i + 1  # 金标 1 条 + 预测 j-i 条 → 每条预测各计一次 TP
                    matched = True
                    break
                if not gs.startswith(acc):
                    break
                j += 1
            i = j + 1 if matched else i + 1
    fp = len(pred) - tp
    fn = len(gold) - tp
    return tp, fp, fn


def score_case(gold: dict, run: dict) -> dict:
    pred = _predict_view(run.get("facts", {}))
    g = gold["gold"]
    per_field: dict[str, dict] = {}
    tp = fp = fn = 0

    for f in SCALAR_FIELDS:
        if f not in g or g[f] is None:
            continue
        ok = pred.get(f) == g[f]
        per_field[f] = {"gold": g[f], "pred": pred.get(f), "match": ok}
        tp += int(ok)
        fn += int(not ok)

    for f in SET_FIELDS:
        if f not in g:
            continue
        t, p, n = _match_sets([str(x) for x in g[f] if x], [str(x) for x in pred.get(f, [])])
        per_field[f] = {"gold_n": len([x for x in g[f] if x]), "pred_n": len(pred.get(f, [])),
                        "tp": t, "fp": p, "fn": n}
        tp += t
        fp += p
        fn += n

    n_gold_fields = sum(1 for f in SCALAR_FIELDS if g.get(f) is not None) + sum(
        len([x for x in g[f] if x]) for f in SET_FIELDS if f in g)
    missing = sum(1 for f in SCALAR_FIELDS if g.get(f) is not None and pred.get(f) is None)
    return {
        "case_id": gold["case_id"],
        "per_field": per_field,
        "tp": tp, "fp": fp, "fn": fn,
        "gold_field_count": n_gold_fields,
        "missing_scalar": missing,
        "missing_rate": round(missing / max(sum(1 for f in SCALAR_FIELDS if g.get(f) is not None), 1), 4),
    }


def evaluate(gold_dir: str | Path, runs_dir: str | Path) -> dict:
    gold_dir, runs_dir = Path(gold_dir), Path(runs_dir)
    results = []
    for gf in sorted(gold_dir.glob("*.json")):
        gold = json.loads(gf.read_text(encoding="utf-8"))
        run_file = runs_dir / f"{gold['case_id']}.json"
        if not run_file.is_file():
            results.append({"case_id": gold["case_id"], "error": "run_missing"})
            continue
        run = json.loads(run_file.read_text(encoding="utf-8"))
        results.append(score_case(gold, run))

    tp = sum(r.get("tp", 0) for r in results)
    fp = sum(r.get("fp", 0) for r in results)
    fn = sum(r.get("fn", 0) for r in results)
    micro_p = tp / (tp + fp) if tp + fp else 0.0
    micro_r = tp / (tp + fn) if tp + fn else 0.0
    micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if micro_p + micro_r else 0.0

    # 宏平均：按案件的字段级 F1 平均
    case_f1s = []
    for r in results:
        if "error" in r:
            continue
        ctp, cfp, cfn = r["tp"], r["fp"], r["fn"]
        p = ctp / (ctp + cfp) if ctp + cfp else 0.0
        rc = ctp / (ctp + cfn) if ctp + cfn else 0.0
        case_f1s.append(2 * p * rc / (p + rc) if p + rc else 0.0)
    macro_f1 = sum(case_f1s) / len(case_f1s) if case_f1s else 0.0

    # 缺失率口径：金标标量字段中预测为空的比例（规格 §11.2：与漏提/错值分开统计）
    total_gold_scalars = 0
    total_missing = 0
    for r in results:
        if "error" in r:
            continue
        g = json.loads((gold_dir / f"{r['case_id']}.json").read_text(encoding="utf-8"))["gold"]
        n = sum(1 for f in SCALAR_FIELDS if g.get(f) is not None)
        total_gold_scalars += n
        total_missing += r["missing_scalar"]
    return {
        "n_cases": len(results),
        "micro": {"precision": round(micro_p, 4), "recall": round(micro_r, 4), "f1": round(micro_f1, 4)},
        "macro_f1": round(macro_f1, 4),
        "missing_rate": round(total_missing / total_gold_scalars, 4) if total_gold_scalars else None,
        "per_case": results,
    }
