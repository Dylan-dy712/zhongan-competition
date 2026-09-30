"""生成标注工作包：每案一个自包含 JSON（机器预填 + OCR 全文）+ 原图 + 须知。

产出结构（--out 目录）：
  gold/<case_id>.json      标注人只改 gold / labels 两个字段
  images/<case_id>/*.jpg   该案原始扫描件（对照疑难字段）
  README-标注须知.md       五分钟上手说明
  _recommended.txt         推荐标注案件清单（分层抽样）

用法：
  python scripts/gen_gold_pack.py --runs-dir <runs> --bundles-dir <bundles> \
      --dataset-dir <dataset> --out <pack目录> [--cases A,B,...] [--n 15]
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GOLD_FIELDS = ["hospital", "admission_date", "discharge_date", "stay_days",
               "total_cost_minor", "self_paid_minor", "diagnoses", "procedures", "medications"]
LABEL_CODES = [
    "CLIN_MEDICATION_CONTEXT_REVIEW", "CLIN_EXAM_JUSTIFICATION_REVIEW",
    "COST_SELF_PAY_DEVIATION", "COST_AMOUNT_RECONCILIATION",
    "EXP_TERMINOLOGY_BARRIER", "EXP_DISCHARGE_GUIDANCE_GAP",
]


def _pred_view(run: dict) -> dict:
    facts = run.get("facts", {})
    enc = (facts.get("encounters") or [{}])[0]

    def v(fv):
        return fv.get("value") if fv else None

    exp = facts.get("expenses", [])
    total = next((e["amount_minor"]["value"] for e in exp
                  if e.get("scope") == "total" and e.get("amount_minor", {}).get("value") is not None), None)
    selfp = next((e["amount_minor"]["value"] for e in exp
                  if e.get("scope") == "self_paid" and e.get("amount_minor", {}).get("value") is not None), None)
    return {
        "hospital": v(enc.get("hospital")),
        "admission_date": v(enc.get("admission_date")),
        "discharge_date": v(enc.get("discharge_date")),
        "stay_days": v(enc.get("stay_days")),
        "total_cost_minor": total,
        "self_paid_minor": selfp,
        "diagnoses": [d["name"]["value"] for d in facts.get("diagnoses", []) if d.get("name", {}).get("value")],
        "procedures": [p["name"]["value"] for p in facts.get("procedures", []) if p.get("name", {}).get("value")],
        "medications": [m["name"]["value"] for m in facts.get("medications", []) if m.get("name", {}).get("value")],
    }


def pick_cases(runs: list[dict], bundles_dir: Path, n: int, seed: int = 11) -> list[str]:
    """分层：富文书住院案(结算单/病案首页) + 门诊为主案 + 警告案，保证形态多样性。"""
    rng = random.Random(seed)
    strata = {"rich": [], "outpatient": [], "other": []}
    for r in runs:
        cid = r["case_id"]
        b = json.loads((bundles_dir / f"{cid}.json").read_text(encoding="utf-8"))
        types = {p["classification"]["doc_type"] for p in b["pages"]}
        if {"insurance_settlement", "medical_record_front"} & types:
            strata["rich"].append(cid)
        elif "outpatient_record" in types and "discharge_summary" not in types:
            strata["outpatient"].append(cid)
        else:
            strata["other"].append(cid)
    picked = []
    per = {"rich": max(4, n // 2), "outpatient": max(3, n // 4), "other": n}
    for k, cap in per.items():
        pool = sorted(strata[k])
        rng.shuffle(pool)
        picked.extend(pool[:cap])
    return picked[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", required=True)
    ap.add_argument("--bundles-dir", required=True)
    ap.add_argument("--dataset-dir", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--with-images", action="store_true", default=True)
    opts = ap.parse_args()

    runs_dir, bundles_dir, out = Path(opts.runs_dir), Path(opts.bundles_dir), Path(opts.out)
    runs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(runs_dir.glob("*.json"))]
    by_id = {r["case_id"]: r for r in runs}

    cases = [c for c in opts.cases.split(",") if c] if opts.cases else pick_cases(runs, bundles_dir, opts.n)
    (out / "gold").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(parents=True, exist_ok=True)

    for cid in cases:
        run = by_id[cid]
        bundle = json.loads((bundles_dir / f"{cid}.json").read_text(encoding="utf-8"))
        pred = _pred_view(run)
        fired = {i["label_code"] for i in run.get("insights", [])}
        gold_template = {k: pred.get(k) for k in GOLD_FIELDS}
        labels = {code: {"present": code in fired,
                         "severity": next((i["severity"] for i in run.get("insights", [])
                                           if i["label_code"] == code), None)}
                  for code in LABEL_CODES}
        ocr_text = "\n\n".join(
            f"===== [{p['classification']['doc_type']}] {p['file'].split('/')[-1]} =====\n{p.get('text','')}"
            for p in bundle["pages"]
        )
        doc = {
            "case_id": cid,
            "_说明": "只修改 gold 与 labels 两个字段；_pred_for_reference 是机器预填仅供参考（可能有错，正是要你核对的对象）；_ocr_text 是 OCR 全文（字段疑问先查这里，再看原图）。金额单位=分。材料中确实不存在的字段填 null。labels 六类必须每类给出 present(true/false) 与 severity(low/medium/high，present=false 时填 null)。",
            "gold": gold_template,
            "labels": labels,
            "_pred_for_reference": pred,
            "_ocr_text": ocr_text,
        }
        (out / "gold" / f"{cid}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

        if opts.with_images and opts.dataset_dir:
            src_case = Path(opts.dataset_dir) / cid
            if src_case.is_dir():
                dst = out / "images" / cid
                dst.mkdir(exist_ok=True)
                for img in src_case.iterdir():
                    if img.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                        shutil.copy2(img, dst / img.name)

    (out / "_recommended.txt").write_text("\n".join(cases), encoding="utf-8")
    readme = f"""# 标注须知（5 分钟上手）

本包含 {len(cases)} 个案件。每个案件 = gold/{'<case>'}.json + images/<case>/ 原图。

## 你要做的事
1. 打开 gold/<case>.json，对照 _ocr_text（OCR 全文）和 images/ 原图，逐字段核对：
   - **gold**：机器预填值可能对也可能错，以你看到的原文为准修改。日期 YYYY-MM-DD；金额单位=分（原文 54131.20 元 → 5413120）。
   - **labels**：六类痛点，每类给出 present（材料是否支持该痛点存在）与 severity。判定标准见《docs/evaluation/annotation-guide.md》（含正反例）。
2. 材料里**确实没有**的信息：gold 对应字段填 null（不计入评分）；**有但机器漏了**：你补上（这就是机器的漏报）。
3. 拿不准的字段：保留机器值并在 "_说明" 下方追加 "_unsure": ["字段名"]，评分时该字段剔除。
4. 每案约 10-15 分钟。改完的 json 按原文件名传回。

## KR3 盲评（另一件事，10 分钟/份）
blind/ 目录下的 blind_XXXXXXXX.html 是匿名报告：独立读完后，在 scoresheet.csv 按编号填
温度感(1-5)、可行动性(1-5)、医学事实错误(有/无/不确定)。三人互不通气。
"""
    (out / "README-标注须知.md").write_text(readme, encoding="utf-8")
    print(f"pack: {len(cases)} cases -> {out}")
    print("cases:", ",".join(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
