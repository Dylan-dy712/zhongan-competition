"""Batch OCR over the de-identified claim dataset.

Reads images from --dataset-dir (case folders with page images) and writes one
JSON per image to --ocr-dir, preserving the case folder structure. Each output
contains normalized text lines with scores and bboxes plus the joined text, so
downstream stages never need to re-run OCR.

Windows notes: cv2.imread cannot open non-ASCII paths, so images are read via
np.fromfile + imdecode. ProcessPoolExecutor deadlocked with onnxruntime workers
on win32, so parallelism is achieved by launching several single-process shards
(--shard i --shards N) instead of an inner pool.

Usage:
    python scripts/batch_ocr.py --dataset-dir <dir> --ocr-dir <dir> \
        [--shard 0 --shards 6] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_IMG_EXT = {".jpg", ".jpeg", ".png"}
_PER_IMAGE_TIMEOUT_S = 300


def _read_image(path: str):
    import cv2
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _ocr_one(ocr, src: str, rel: str) -> dict:
    img = _read_image(src)
    h, w = img.shape[:2] if img is not None else (None, None)
    if img is None:
        return {
            "source_ref": rel, "image_size": {"w": None, "h": None},
            "parser": "rapidocr-onnxruntime", "parser_version": "0.4.x",
            "lines": [], "text": "", "ocr_status": "unreadable",
        }
    result, _elapsed = ocr(img)
    lines = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            lines.append(
                {
                    "text": text,
                    "score": round(float(score), 4),
                    # spec 5.3: bbox [x0,y0,x1,y1] normalized to [0,1]
                    "bbox": [
                        round(x0 / w, 4) if w else None,
                        round(y0 / h, 4) if h else None,
                        round(x1 / w, 4) if w else None,
                        round(y1 / h, 4) if h else None,
                    ],
                }
            )
    return {
        "source_ref": rel, "image_size": {"w": w, "h": h},
        "parser": "rapidocr-onnxruntime", "parser_version": "0.4.x",
        "lines": lines, "text": "\n".join(l["text"] for l in lines),
        "ocr_status": "ok" if lines else "empty",
    }


def main() -> int:
    os.environ.setdefault("OMP_NUM_THREADS", "5")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-dir", required=True)
    ap.add_argument("--ocr-dir", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    opts = ap.parse_args()

    from rapidocr_onnxruntime import RapidOCR

    dataset = Path(opts.dataset_dir)
    out_root = Path(opts.ocr_dir)
    tasks: list[tuple[str, str]] = []
    for case_dir in sorted(p for p in dataset.iterdir() if p.is_dir()):
        for img in sorted(case_dir.iterdir()):
            if img.suffix.lower() not in _IMG_EXT:
                continue
            tasks.append((str(img), f"{case_dir.name}/{img.name}"))
    tasks = [t for i, t in enumerate(tasks) if i % opts.shards == opts.shard]
    tasks = [t for t in tasks if not (out_root / Path(t[1]).parent / (Path(t[1]).stem + ".json")).exists()]
    if opts.limit:
        tasks = tasks[: opts.limit]
    print(f"[shard {opts.shard}/{opts.shards}] pending: {len(tasks)}", flush=True)
    if not tasks:
        return 0

    ocr = RapidOCR()
    done = failed = 0
    t0 = time.time()
    for src, rel in tasks:
        ts = time.time()
        try:
            if time.time() - ts > _PER_IMAGE_TIMEOUT_S:
                raise TimeoutError("per-image watchdog")
            payload = _ocr_one(ocr, src, rel)
        except Exception as exc:  # noqa: BLE001 - keep batch alive, record failure
            failed += 1
            print(f"FAILED {rel}: {exc}", flush=True)
            continue
        dst = out_root / Path(rel).parent / (Path(rel).stem + ".json")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(dst)
        done += 1
        n = done + failed
        if n % 10 == 0:
            rate = n / (time.time() - t0)
            eta = (len(tasks) - n) / rate / 60 if rate > 0 else -1
            print(f"[shard {opts.shard}] {n}/{len(tasks)} {rate:.2f} img/s eta {eta:.0f}min", flush=True)
    print(f"[shard {opts.shard}] done={done} failed={failed} elapsed={(time.time()-t0)/60:.1f}min", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
