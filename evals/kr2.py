"""KR2 评测：痛点识别与专家标注一致率。

金标格式：{case_id, labels: {"LABEL_CODE": {"present": true, "severity": "low"}}}
- present=false 表示专家判定该案不存在此痛点；
- 一致率口径（内部 v0.1）：按 案件×标签 判断机会统计，预测 present 与金标一致
  计为一致；另有标签级 P/R/F1 与严重度一致（仅对双方均 present 的机会统计）。
"""

from __future__ import annotations

import json
from pathlib import Path


def score_case(gold: dict, run: dict) -> dict:
    pred_labels = {i["label_code"]: i for i in run.get("insights", [])}
    gold_labels = gold.get("labels", {})
    keys = sorted(set(gold_labels) | set(pred_labels))
    agree = 0
    severity_agree = 0
    severity_total = 0
    tp = fp = fn = 0
    for k in keys:
        g = gold_labels.get(k, {}).get("present", False)
        p = k in pred_labels
        if g == p:
            agree += 1
        if p and g:
            tp += 1
            sev_g = gold_labels[k].get("severity")
            sev_p = pred_labels[k].get("severity")
            if sev_g and sev_p:
                severity_total += 1
                severity_agree += int(sev_g == sev_p)
        elif p and not g:
            fp += 1
        elif g and not p:
            fn += 1
    return {
        "case_id": gold["case_id"],
        "opportunities": len(keys),
        "agreements": agree,
        "agreement_rate": round(agree / len(keys), 4) if keys else None,
        "tp": tp, "fp": fp, "fn": fn,
        "severity_agree": f"{severity_agree}/{severity_total}",
    }


def evaluate(gold_dir: str | Path, runs_dir: str | Path) -> dict:
    gold_dir, runs_dir = Path(gold_dir), Path(runs_dir)
    per_case = []
    for gf in sorted(gold_dir.glob("*.json")):
        gold = json.loads(gf.read_text(encoding="utf-8"))
        run_file = runs_dir / f"{gold['case_id']}.json"
        if not run_file.is_file():
            per_case.append({"case_id": gold["case_id"], "error": "run_missing"})
            continue
        run = json.loads(run_file.read_text(encoding="utf-8"))
        per_case.append(score_case(gold, run))

    valid = [c for c in per_case if "error" not in c]
    opp = sum(c["opportunities"] for c in valid)
    agr = sum(c["agreements"] for c in valid)
    tp = sum(c["tp"] for c in valid)
    fp = sum(c["fp"] for c in valid)
    fn = sum(c["fn"] for c in valid)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "n_cases": len(valid),
        "overall_agreement": round(agr / opp, 4) if opp else None,
        "label_prf": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        },
        "per_case": per_case,
    }
