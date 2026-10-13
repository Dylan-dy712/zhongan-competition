# -*- coding: utf-8 -*-
"""Compile docs/medical/knowledge/**/*.md into contracts/knowledge/entries.jsonl.

Parses both entry formats produced by the knowledge drafting pipeline:
  - list format:   "- **ID**：CODE-Sn-nn｜title" blocks with bold fields
  - table format:  "| ID | col | col |..." rows (S2/S5) + trailing 公共字段声明

Every compiled entry is validated with the Pydantic contract
(services/api/app/contracts/knowledge.py). Validation failures abort the build
with a nonzero exit; the JSONL is only rewritten when ALL entries pass.
"""

import json
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.contracts.knowledge import DiseaseCode, KnowledgeBuildReport, KnowledgeEntry, KnowledgePackMeta, KnowledgeStatus  # noqa: E402

KNOWLEDGE_DIR = REPO / "docs" / "medical" / "knowledge"
OUT_DIR = REPO / "contracts" / "knowledge"

FIELD_RE = re.compile(r"^- \*\*(.+?)\*\*：\s*(.*)$")
ID_LINE_RE = re.compile(r"^- \*\*ID\*\*：\s*(.+)$")
COMMON_RE = re.compile(r"^- \*\*(适用范围|锚定|来源|状态)\*\*：\s*(.*)$", re.M)

DISEASE_BY_PACK = {
    "KP-FX": "FX",
    "KP-FY": "FY",
    "KP-GX": "GX",
    "KP-YZ": "YZ",
    "KP-TN": "TN",
    "KP-HJ": "HJ",
    "KP-TY": "TY",
}


def normalise_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip() or None


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a mapping")
    return meta, text[m.end():]


def parse_list_entries(body: str, slot: str) -> tuple[list[dict], int]:
    """Parse '- **ID**：...' blocks. Returns (entries, raw_id_occurrences)."""
    entries = []
    raw = 0
    blocks = re.split(r"(?m)^(?=- \*\*ID\*\*：)", body)
    for block in blocks:
        if not block.strip():
            continue
        first = ID_LINE_RE.match(block.split("\n")[0])
        if not first:
            continue
        fields = {}
        for line in block.split("\n"):
            fm = FIELD_RE.match(line.strip())
            if fm:
                key, value = fm.group(1), fm.group(2).strip()
                fields[key] = (fields.get(key, "") + (" " + value if key in fields else value)).strip()
        id_value = first.group(1)
        raw += 1
        if "｜" in id_value:
            entry_id, title = id_value.split("｜", 1)
        else:
            entry_id, title = id_value, None
        content = fields.get("内容", "")
        entries.append(
            {
                "entry_id": entry_id.strip(),
                "slot": slot,
                "title": title or None,
                "applicable_scope": fields.get("适用范围"),
                "content": content,
                "anchoring": fields.get("锚定"),
                "purposes_raw": fields.get("用途", ""),
                "source": fields.get("来源"),
                "status": fields.get("状态", "draft-待医学审核"),
                "origin_format": "list",
            }
        )
    return entries, raw


def split_table_rows(body: str) -> tuple[dict[str, list[tuple[dict, str]]], str]:
    """Extract markdown tables keyed by slot, plus the trailing 公共字段声明 text."""
    tables: dict[str, list[tuple[dict, str]]] = {}
    common = ""
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i].lstrip())
                i += 1
            rows = [ln for ln in block if re.match(r"^\|[-\s|:]+\|$", ln.strip()) is None]
            if len(rows) >= 2:
                header = [c.strip() for c in rows[0].strip().strip("|").split("|")]
                for row in rows[1:]:
                    cells = [c.strip() for c in row.strip().strip("|").split("|")]
                    if not cells or not cells[0]:
                        continue
                    id_m = re.match(r"^[A-Z]{2}-S\d{1,2}-\d{2}$", cells[0])
                    if not id_m:
                        continue
                    slot = re.match(r"^([A-Z]{2}-S\d{1,2})-", cells[0]).group(1).split("-")[1]
                    slot = "S" + slot.split("S", 1)[1]
                    named = {"ID": cells[0]}
                    for idx, name in enumerate(header):
                        if idx == 0 or idx >= len(cells):
                            continue
                        named[name] = cells[idx]
                    tables.setdefault(slot, []).append((named, row.strip()))
        else:
            if "公共字段声明" in lines[i]:
                common = "\n".join(lines[i : i + 12])
            i += 1
    return tables, common


def parse_table_entries(body: str, slot: str, pack_code: str) -> tuple[list[dict], int]:
    tables, common = split_table_rows(body)
    slot_key = slot if slot != "TY" else "TY"
    entries = []
    raw = 0
    common_fields = dict(COMMON_RE.findall(common))
    for named, _row in tables.get(slot_key, []):
        entry_id = None
        title = None
        purposes_raw = ""
        content_parts = []
        for name, value in named.items():
            if name == "ID":
                entry_id = value
                raw += 1
            elif name in ("术语/常见写法", "指引项"):
                title = value
            elif name == "用途":
                purposes_raw = value
            else:
                content_parts.append(f"{name}：{value}")
        if entry_id is None:
            continue
        anchoring_m = re.search(r"锚定[:：]\s*([^；;）)]+)[；;）)]?", "；".join(content_parts))
        entries.append(
            {
                "entry_id": entry_id,
                "slot": slot,
                "title": title,
                "applicable_scope": common_fields.get("适用范围"),
                "content": "\n".join(content_parts) or title or "",
                "anchoring": common_fields.get("锚定") or (anchoring_m.group(1).strip() if anchoring_m else None),
                "purposes_raw": purposes_raw or "",
                "source": common_fields.get("来源"),
                "status": common_fields.get("状态", "draft-待医学审核"),
                "origin_format": "table",
            }
        )
    return entries, raw


def split_purposes(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[/／]", raw)
    return [p.strip() for p in parts if p.strip()]


def build_entry(base: dict, pack_id: str, disease: str, slot_file: str) -> KnowledgeEntry:
    status_value = base.get("status", "draft-待医学审核")
    status_note = None
    reviewed_by = None
    reviewed_at = None
    status_main = status_value
    note_m = re.search(r"[（(](.+)[）)]\s*$", status_value)
    if note_m and status_value.startswith("draft-待医学审核（"):
        status_main = "draft-待医学审核"
        status_note = note_m.group(1)
    approved_m = re.fullmatch(r"approved-([^-]+)-(\d{4}-\d{2}-\d{2})", status_value)
    if approved_m:
        status_main = "approved"
        reviewed_by = approved_m.group(1)
        reviewed_at = approved_m.group(2)
    if not status_main.startswith("draft") and status_main != "approved":
        raise ValueError(f"unsupported knowledge status: {status_value}")
    content = base.get("content", "")
    return KnowledgeEntry(
        entry_id=base["entry_id"],
        pack_id=pack_id,
        disease_code=DiseaseCode(disease),
        slot=base["slot"],
        slot_file=slot_file,
        title=base.get("title"),
        applicable_scope=base.get("applicable_scope"),
        content=content,
        anchoring=base.get("anchoring"),
        purposes=split_purposes(base.get("purposes_raw", "")),
        source=base.get("source"),
        status=KnowledgeStatus.draft if status_main.startswith("draft") else KnowledgeStatus.approved,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        status_note=status_note,
        numeric_pending_review="【数值待医学审核】" in content,
        platform_verified=bool(status_note and "氢离子平台查证" in status_note),
        ai_verified=True,
        ai_verification_source="user_attested_professional_medical_agent",
        origin_format=base.get("origin_format", "list"),
    )


def compile_pack(pack_dir: Path) -> tuple[list[KnowledgeEntry], KnowledgePackMeta]:
    index_path = pack_dir / "_index.md"
    if index_path.exists():
        meta, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
        pack_id = meta.get("pack_id", "")
    else:
        meta, pack_id = {}, ""
    disease = DISEASE_BY_PACK.get(pack_id)
    if not disease:
        raise ValueError(f"cannot resolve pack for {pack_dir.name}: pack_id={pack_id!r}")
    entries: list[KnowledgeEntry] = []
    slot_counts: dict[str, int] = {}
    seen_ids: set[str] = set()
    for slot_file in sorted(pack_dir.glob("S*.md")):
        raw_text = slot_file.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(raw_text)
        slot = fm.get("slot") or re.search(r"^## (S\d{1,2})", body, re.M).group(1)
        table_entries, table_raw = parse_table_entries(body, slot, disease)
        list_entries, list_raw = parse_list_entries(body, slot)
        parsed = table_entries if table_entries else list_entries
        for base in parsed:
            entry = build_entry(base, pack_id, disease, slot_file.name)
            if entry.entry_id in seen_ids:
                raise ValueError(f"duplicate entry id {entry.entry_id} in {pack_dir.name}")
            seen_ids.add(entry.entry_id)
            entries.append(entry)
        slot_counts[slot] = len(parsed)
    pack_meta = KnowledgePackMeta(
        pack_id=pack_id,
        disease_code=DiseaseCode(disease),
        version=meta.get("version", "0.1.0-draft"),
        status=KnowledgeStatus.draft,
        scope=normalise_text(meta.get("scope")),
        exclusions=normalise_text(meta.get("exclusions")),
        entries_total=len(entries),
        slot_counts=dict(sorted(slot_counts.items())),
    )
    return entries, pack_meta


def main() -> int:
    pack_dirs = sorted(
        p for p in KNOWLEDGE_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")
    )
    all_entries: list[KnowledgeEntry] = []
    pack_metas: list[KnowledgePackMeta] = []
    for pack_dir in pack_dirs:
        entries, meta = compile_pack(pack_dir)
        all_entries.extend(entries)
        pack_metas.append(meta)
        print(f"{meta.pack_id}: {meta.entries_total} entries  slots={meta.slot_counts}")
    # TY single-file pack
    ty_file = KNOWLEDGE_DIR / "通用-费用与医保术语.md"
    ty_entries: list[KnowledgeEntry] = []
    ty_meta = None
    if ty_file.exists():
        fm, body = parse_frontmatter(ty_file.read_text(encoding="utf-8"))
        parsed, _ = parse_list_entries(body, "TY")
        if not parsed:
            parsed, _ = parse_table_entries(body, "TY", "TY")
        for base in parsed:
            if not base["entry_id"].startswith("TY-"):
                continue
            ty_entries.append(build_entry(base, "KP-TY", "TY", "通用-费用与医保术语.md"))
        ty_meta = KnowledgePackMeta(
            pack_id="KP-TY",
            disease_code=DiseaseCode.ty,
            version=fm.get("version", "0.1.0-draft"),
            status=KnowledgeStatus.draft,
            scope=fm.get("scope") or fm.get("用途"),
            exclusions=None,
            entries_total=len(ty_entries),
            slot_counts={"TY": len(ty_entries)},
        )
        all_entries.extend(ty_entries)
        pack_metas.append(ty_meta)
        print(f"KP-TY: {len(ty_entries)} entries")

    validation_errors: list[str] = []
    for entry in all_entries:
        try:
            entry.model_validate(entry.model_dump())
        except Exception as exc:  # noqa: BLE001
            validation_errors.append(f"{entry.entry_id}: {exc}")

    serialized_entries = "".join(entry.model_dump_json() + "\n" for entry in all_entries)
    content_sha256 = hashlib.sha256(serialized_entries.encode("utf-8")).hexdigest()
    report = KnowledgeBuildReport(
        built_at=datetime.now(timezone.utc).isoformat(),
        packs=pack_metas,
        entries_total=len(all_entries),
        content_sha256=content_sha256,
        validation_errors=validation_errors,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if validation_errors:
        (OUT_DIR / "build-report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        for err in validation_errors:
            print("VALIDATION ERROR:", err, file=sys.stderr)
        print(f"FAILED: {len(validation_errors)} validation errors", file=sys.stderr)
        return 1
    # Write exact UTF-8 bytes so the content hash is identical on Windows/Linux.
    (OUT_DIR / "entries.jsonl").write_bytes(serialized_entries.encode("utf-8"))
    (OUT_DIR / "build-report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"OK: {len(all_entries)} entries -> {OUT_DIR / 'entries.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
