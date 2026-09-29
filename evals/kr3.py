"""KR3 盲评脚手架：去标识打包、随机编号、量表录入与汇总。

协议（spec §11.4）：
- 同一病例的背景摘要固定版，保证评审间事实一致；
- 报告随机编号、顺序随机、隐藏方案名与生成模式；
- 每份报告 >= 3 名独立读者；医学错误不由温度分抵消（单独记录）；
- 无效/无法评分单列，不静默删除。
"""

from __future__ import annotations

import csv
import json
import random
import uuid
from pathlib import Path

ANCHORS = {
    "温度感": {
        1: "责备、空泛保证或明显忽略经历",
        3: "礼貌易读，但多数表达可用于任意同病种患者",
        5: "准确承接当前经历/关注点，尊重不确定性，安抚具体而不过度保证",
    },
    "可行动性": {
        1: "无具体动作，或动作无依据不可执行",
        3: "有动作但与当前事实联系弱，执行者/渠道不清楚",
        5: "行动与病例需求对应，优先级、执行者、确认路径清楚",
    },
}


def package_blind(runs_dir: str | Path, out_dir: str | Path, n_cases: int = 9, seed: int = 7) -> dict:
    """把 N 份报告打成盲评包：random_id.html 内容 + 对照用 mapping（评审不可见）。"""
    rng = random.Random(seed)
    runs = sorted(Path(runs_dir).glob("*.json"))
    # 优先 live 模式且六段完整的报告
    eligible = []
    for f in runs:
        r = json.loads(f.read_text(encoding="utf-8"))
        rep = r.get("report", {})
        if r["stages"].get("guidance", {}).get("mode") in ("live",) and len(rep.get("sections", [])) == 6:
            eligible.append(r)
    picked = rng.sample(eligible, min(n_cases, len(eligible)))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mapping = []
    for r in picked:
        rid = uuid.uuid4().hex[:8].upper()
        facts = r["facts"]
        enc = (facts.get("encounters") or [{}])[0]
        dx = "；".join(d["name"]["value"] for d in facts.get("diagnoses", []) if d.get("name", {}).get("value"))[:120]
        bg = (
            f"背景摘要（固定版）：{enc.get('hospital', {}).get('value') or '某医院'}，"
            f"{(enc.get('admission_date') or {}).get('value') or '?'} 入院至 "
            f"{(enc.get('discharge_date') or {}).get('value') or '?'} 出院"
            f"（住院 {(enc.get('stay_days') or {}).get('value') or '?'} 天）；"
            f"诊断：{dx}。"
        )
        sections_html = "".join(
            f"<div class='sec'><h3>{s['title_zh']}</h3><p>{s['content']}</p></div>" for s in r["report"]["sections"]
        )
        actions_html = "".join(
            f"<li>{a['action_text']}（{a.get('rationale') or ''}）</li>" for a in r["report"].get("actions", [])
        )
        html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>盲评 {rid}</title>
<style>body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;max-width:720px;margin:24px auto;padding:0 16px;color:#333;line-height:1.7}}
.sec{{border:1px solid #e5e0d8;border-radius:10px;padding:14px 18px;margin:10px 0}}.sec p{{white-space:pre-wrap}}
.bg{{background:#f6f2ec;border-radius:10px;padding:12px 16px}}h3{{margin:0 0 6px}}</style></head><body>
<h2>关怀报告 · 盲评编号 {rid}</h2>
<div class="bg">{bg}</div>
<h4>优先行动</h4><ul>{actions_html}</ul>
{sections_html}
</body></html>"""
        (out / f"blind_{rid}.html").write_text(html, encoding="utf-8")
        mapping.append({"blind_id": rid, "case_id": r["case_id"]})
    (out / "_mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")

    # 评分表（每读者一份 CSV）
    with (out / "scoresheet.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["读者编号", "盲评编号", "温度感(1-5)", "可行动性(1-5)", "医学事实错误(有/无/不确定)", "备注"])
    return {"n_packaged": len(mapping), "out_dir": str(out)}


def summarize(scores_csv: str | Path, mapping_json: str | Path) -> dict:
    """汇总：按病例聚合读者均分；两维度分别报告均值/离散/分布（spec §11.4）。"""
    mapping = {m["blind_id"]: m["case_id"] for m in json.loads(Path(mapping_json).read_text(encoding="utf-8"))}
    rows = list(csv.DictReader(open(scores_csv, encoding="utf-8-sig")))
    by_case: dict[str, dict] = {}
    invalid = 0
    for r in rows:
        try:
            warmth = float(r["温度感(1-5)"])
            action = float(r["可行动性(1-5)"])
        except (ValueError, KeyError):
            invalid += 1
            continue
        case = mapping.get(r.get("盲评编号", ""), "?")
        by_case.setdefault(case, {"warmth": [], "action": [], "med_err": []})
        by_case[case]["warmth"].append(warmth)
        by_case[case]["action"].append(action)
        by_case[case]["med_err"].append(r.get("医学事实错误(有/无/不确定)", ""))

    def _agg(vals: list[float]) -> dict:
        return {"mean": round(sum(vals) / len(vals), 2), "min": min(vals), "max": max(vals), "n": len(vals)}

    all_w = [v for c in by_case.values() for v in c["warmth"]]
    all_a = [v for c in by_case.values() for v in c["action"]]
    return {
        "invalid_rows": invalid,
        "overall": {"warmth": _agg(all_w) if all_w else None, "actionability": _agg(all_a) if all_a else None},
        "per_case": {c: {"warmth": _agg(d["warmth"]), "actionability": _agg(d["action"]),
                         "medical_error_flags": sum(1 for e in d["med_err"] if e == "有")}
                     for c, d in by_case.items()},
    }
