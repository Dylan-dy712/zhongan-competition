"""案件捆束构建：把一案的 OCR 页 JSON 合并为分类后的 bundle，供抽取阶段消费。

bundle 是离线流水线与 API 服务共用的输入单元；其中 document_id 由
source_ref 哈希派生，保证重跑幂等。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def _group_key(filename: str) -> str:
    """同一份材料的多页共享组键：去掉结尾 _N_timestamp 或 -N 序号。"""
    stem = Path(filename).stem
    stem = re.sub(r"_\d+_\d+$", "", stem)
    stem = re.sub(r"-\d+$", "", stem)
    return stem or filename


def _stable_id(source_ref: str) -> str:
    return hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]


def build_bundle(case_id: str, page_jsons: list[dict]) -> dict:
    """page_jsons: batch_ocr.py 输出的页对象列表（含 source_ref/lines/text）。"""
    from .doc_classify import classify_page

    pages = []
    for idx, p in enumerate(sorted(page_jsons, key=lambda x: x["source_ref"])):
        src_ref = p["source_ref"]
        filename = src_ref.split("/", 1)[-1]
        cls = classify_page(p.get("text", ""), filename_hint=_group_key(filename))
        pages.append(
            {
                "page_uid": _stable_id(src_ref),
                "document_id": _stable_id(_group_key(filename) + "|" + case_id),
                "page_index": idx,
                "file": src_ref,
                "doc_hint": _group_key(filename),
                "image_size": p.get("image_size"),
                "lines": p.get("lines", []),
                "text": p.get("text", ""),
                "ocr_status": p.get("ocr_status", "ok"),
                "classification": cls.to_dict(),
            }
        )

    # 文档级类型：组内按页置信度加权投票
    groups: dict[str, list[dict]] = {}
    for pg in pages:
        groups.setdefault(pg["document_id"], []).append(pg)
    documents = []
    for doc_id, pgs in groups.items():
        votes: dict[str, float] = {}
        for pg in pgs:
            c = pg["classification"]
            votes[c["doc_type"]] = votes.get(c["doc_type"], 0) + max(c["confidence"], 0.1)
        doc_type = max(votes.items(), key=lambda kv: kv[1])[0] if votes else "other"
        per_type_conf = sum(
            pg["classification"]["confidence"]
            for pg in pgs
            if pg["classification"]["doc_type"] == doc_type
        ) / max(len(pgs), 1)
        documents.append(
            {
                "document_id": doc_id,
                "doc_type": doc_type,
                "doc_type_zh": pgs[0]["classification"].get("doc_type_zh", "")
                if doc_type == "other"
                else None,
                "pages": [pg["page_uid"] for pg in pgs],
                "num_pages": len(pgs),
                "doc_hint": pgs[0]["doc_hint"],
                "confidence": round(min(per_type_conf, 0.98), 3),
            }
        )
    for d in documents:
        from .doc_classify import DOC_TYPE_ZH

        d["doc_type_zh"] = DOC_TYPE_ZH.get(d["doc_type"], d["doc_type"])

    return {
        "case_id": case_id,
        "schema_version": "0.1.0",
        "pages": pages,
        "documents": documents,
    }


def load_case_pages(ocr_dir: Path, case_id: str) -> list[dict]:
    case_dir = ocr_dir / case_id
    if not case_dir.is_dir():
        return []
    out = []
    for f in sorted(case_dir.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out
