"""从 OCR 结果构建全部案件的 bundle JSON。

Usage:
    python scripts/build_bundles.py --ocr-dir <dir> --out-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.pipelines.bundle import build_bundle, load_case_pages  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    opts = ap.parse_args()
    ocr_root = Path(opts.ocr_dir)
    out_root = Path(opts.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    n = 0
    for case_dir in sorted(p for p in ocr_root.iterdir() if p.is_dir()):
        pages = load_case_pages(ocr_root, case_dir.name)
        if not pages:
            continue
        bundle = build_bundle(case_dir.name, pages)
        dst = out_root / f"{case_dir.name}.json"
        dst.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        n += 1
    print(f"bundles built: {n} -> {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
