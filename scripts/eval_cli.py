"""评测 CLI：KR1 字段 F1 / KR2 一致率 / 金标模板生成。

Usage:
    python scripts/eval_cli.py kr1  --gold-dir <dir> --runs-dir <dir>
    python scripts/eval_cli.py kr2  --gold-dir <dir> --runs-dir <dir>
    python scripts/eval_cli.py gold-template --runs-dir <dir> --out <file> [--cases A,B]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.kr1 import evaluate as eval_kr1  # noqa: E402
from evals.kr2 import evaluate as eval_kr2  # noqa: E402


def cmd_gold_template(opts) -> int:
    runs_dir = Path(opts.runs_dir)
    cases = opts.cases.split(",") if opts.cases else None
    templates = []
    for f in sorted(runs_dir.glob("*.json")):
        cid = f.stem
        if cases and cid not in cases:
            continue
        r = json.loads(f.read_text(encoding="utf-8"))
        facts = r.get("facts", {})
        enc = (facts.get("encounters") or [{}])[0]
        pred = {
            "hospital": (enc.get("hospital") or {}).get("value"),
            "admission_date": (enc.get("admission_date") or {}).get("value"),
            "discharge_date": (enc.get("discharge_date") or {}).get("value"),
            "stay_days": (enc.get("stay_days") or {}).get("value"),
            "diagnoses": [d["name"]["value"] for d in facts.get("diagnoses", []) if d.get("name", {}).get("value")],
            "procedures": [p["name"]["value"] for p in facts.get("procedures", []) if p.get("name", {}).get("value")],
            "medications": [m["name"]["value"] for m in facts.get("medications", []) if m.get("name", {}).get("value")],
            "total_cost_minor": next((e["amount_minor"]["value"] for e in facts.get("expenses", [])
                                      if e.get("scope") == "total" and e.get("amount_minor", {}).get("value") is not None), None),
            "self_paid_minor": next((e["amount_minor"]["value"] for e in facts.get("expenses", [])
                                     if e.get("scope") == "self_paid" and e.get("amount_minor", {}).get("value") is not None), None),
        }
        insights = {i["label_code"]: {"present": True, "severity": i.get("severity")} for i in r.get("insights", [])}
        templates.append({
            "case_id": cid,
            "_pred_for_reference": pred,  # 供标注人核对，最终金标以人工阅读原文为准
            "gold": {k: None for k in ("hospital", "admission_date", "discharge_date", "stay_days",
                                       "total_cost_minor", "self_paid_minor", "diagnoses", "procedures", "medications")},
            "labels": insights,
        })
    Path(opts.out).parent.mkdir(parents=True, exist_ok=True)
    Path(opts.out).write_text(json.dumps(templates, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"gold templates: {len(templates)} -> {opts.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("kr1"); p1.add_argument("--gold-dir", required=True); p1.add_argument("--runs-dir", required=True)
    p2 = sub.add_parser("kr2"); p2.add_argument("--gold-dir", required=True); p2.add_argument("--runs-dir", required=True)
    p3 = sub.add_parser("gold-template"); p3.add_argument("--runs-dir", required=True); p3.add_argument("--out", required=True)
    p3.add_argument("--cases", default="")
    opts = ap.parse_args()
    if opts.cmd == "kr1":
        res = eval_kr1(opts.gold_dir, opts.runs_dir)
        print(json.dumps({k: v for k, v in res.items() if k != "per_case"}, ensure_ascii=False, indent=1))
        for c in res["per_case"]:
            if "error" in c:
                print("ERROR", c["case_id"], c["error"])
    elif opts.cmd == "kr2":
        res = eval_kr2(opts.gold_dir, opts.runs_dir)
        print(json.dumps({k: v for k, v in res.items() if k != "per_case"}, ensure_ascii=False, indent=1))
    else:
        return cmd_gold_template(opts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
