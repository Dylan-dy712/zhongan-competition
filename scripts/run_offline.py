"""离线批量运行流水线（评测/演示数据准备）。

Usage:
    python scripts/run_offline.py --bundles-dir <dir> --out-dir <dir> [--case CLxxx] [--provider mock]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.pipelines.runner import run_all, run_case  # noqa: E402
from app.pipelines.profile import METRIC_VERSION, POLICY_VERSION  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--case", default="")
    ap.add_argument("--user-context", default="")
    opts = ap.parse_args()

    settings = Settings()
    bundles_root = Path(opts.bundles_dir)
    out_root = Path(opts.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    if opts.case:
        bundle = json.loads((bundles_root / f"{opts.case}.json").read_text(encoding="utf-8"))
        result = run_case(bundle, settings, user_context=opts.user_context)
        dst = out_root / f"{opts.case}.json"
        dst.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"run saved: {dst} (status={result['status']}, guidance={result['stages']['guidance'].get('mode')})")
        return 0

    bundles = []
    for f in sorted(bundles_root.glob("*.json")):
        bundles.append(json.loads(f.read_text(encoding="utf-8")))
    runs, profiles, snapshot_id = run_all(bundles, settings)
    runs_dir = out_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for r in runs:
        (runs_dir / f"{r['case_id']}.json").write_text(
            json.dumps(r, ensure_ascii=False), encoding="utf-8")
    (out_root / "profiles.json").write_text(json.dumps({
        "snapshot_id": snapshot_id,
        "metric_version": METRIC_VERSION,
        "policy_version": POLICY_VERSION,
        "metrics": [m.model_dump(mode="json") for m in profiles],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in runs if r["status"] == "completed")
    print(f"runs: {len(runs)} (completed={ok}), profiles: {len(profiles)} metrics, snapshot={snapshot_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
