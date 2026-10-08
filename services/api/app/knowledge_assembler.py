"""Knowledge assembler — the runtime consumer of contracts/knowledge/entries.jsonl.

Serves knowledge entries for label checks and the six report sections with two
hard gates enforced (spec.md 4.2 版本化知识包, manifest §6 使用红线):

  1. Pack resolution + exclusions: the case's disease code must map to a pack;
     when a case hits a pack's exclusions, callers MUST route to human review
     and no entries are served (PackExcludedError).
  2. Patient-visibility gate: every entry whose status is not approved is
     excluded from patient-visible output. Numeric-pending is retained as an
     additional review signal, never as the only release gate.

This module never rewrites entry content and never invents knowledge; callers
reference entries by entry_id when building knowledge_refs claims.
"""

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from .contracts.knowledge import DiseaseCode, KnowledgeEntry

APPROVED = "approved"

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JSONL = REPO_ROOT / "contracts" / "knowledge" / "entries.jsonl"
DEFAULT_BUILD_REPORT = REPO_ROOT / "contracts" / "knowledge" / "build-report.json"
DEFAULT_KNOWLEDGE_DIR = REPO_ROOT / "docs" / "medical" / "knowledge"


class KnowledgeAssemblerError(Exception):
    """Base error for knowledge assembly failures."""


class UnknownDiseaseError(KnowledgeAssemblerError):
    """The requested disease code has no knowledge pack."""


class PackExcludedError(KnowledgeAssemblerError):
    """The case hits the pack's exclusions; knowledge must not be served."""

    def __init__(self, pack_id: str, exclusions: str):
        self.pack_id = pack_id
        self.exclusions = exclusions
        super().__init__(
            f"case falls outside {pack_id} scope (exclusions: {exclusions}); "
            "route to human medical review"
        )


@dataclass(frozen=True)
class PackScope:
    """Pack-level metadata from the pack's _index.md frontmatter."""

    pack_id: str
    disease_code: DiseaseCode
    version: str
    status: str
    scope: str | None
    exclusions: str | None
    entries_total: int


@dataclass(frozen=True)
class KnowledgeSelection:
    """Result of a selection call: allowed entries plus the blocked audit trail."""

    allowed: list[KnowledgeEntry]
    blocked: list[KnowledgeEntry]
    pack: PackScope


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter without losing folded scalars or lists."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta = yaml.safe_load(text[3:end]) or {}
    if not isinstance(meta, dict):
        raise KnowledgeAssemblerError("knowledge pack frontmatter must be a mapping")
    return meta


def _normalise_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip() or None


def _exclusion_keywords(exclusions: str) -> list[str]:
    """Split the free-text exclusions field on common delimiters."""
    for sep in ("；", ";", "、", "\n"):
        exclusions = exclusions.replace(sep, "|")
    return [part.strip(" ，,（）()") for part in exclusions.split("|") if part.strip()]


class KnowledgeAssembler:
    """Loads the compiled JSONL once and answers selection queries."""

    def __init__(
        self,
        jsonl_path: Path | None = None,
        knowledge_dir: Path | None = None,
        build_report_path: Path | None = None,
    ) -> None:
        self._jsonl_path = jsonl_path or DEFAULT_JSONL
        self._knowledge_dir = knowledge_dir or DEFAULT_KNOWLEDGE_DIR
        self._build_report_path = build_report_path or DEFAULT_BUILD_REPORT
        self._knowledge_version = ""
        self._entries: dict[str, KnowledgeEntry] = {}
        self._pack_scopes: dict[DiseaseCode, PackScope] = {}
        self._load()

    # ------------------------------------------------------------------ load

    def _load(self) -> None:
        if not self._jsonl_path.exists():
            raise KnowledgeAssemblerError(
                f"knowledge JSONL missing: {self._jsonl_path}; "
                "run tools/build_knowledge_jsonl.py first"
            )
        raw_jsonl = self._jsonl_path.read_bytes()
        if not self._build_report_path.exists():
            raise KnowledgeAssemblerError(
                f"knowledge build report missing: {self._build_report_path}"
            )
        report = json.loads(self._build_report_path.read_text(encoding="utf-8"))
        actual_hash = hashlib.sha256(raw_jsonl).hexdigest()
        if report.get("content_sha256") != actual_hash:
            raise KnowledgeAssemblerError("knowledge JSONL does not match build report hash")
        self._knowledge_version = f"knowledge:sha256:{actual_hash}"
        counts_by_pack: dict[str, int] = {}
        for line in raw_jsonl.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = KnowledgeEntry.model_validate_json(line)
            if entry.entry_id in self._entries:
                raise KnowledgeAssemblerError(
                    f"duplicate entry_id in compiled JSONL: {entry.entry_id}"
                )
            self._entries[entry.entry_id] = entry
            counts_by_pack[entry.pack_id] = counts_by_pack.get(entry.pack_id, 0) + 1
        if report.get("entries_total") != len(self._entries):
            raise KnowledgeAssemblerError("knowledge entry count does not match build report")

        for pack_dir in sorted(self._knowledge_dir.iterdir()):
            if not pack_dir.is_dir() or pack_dir.name.startswith("_"):
                continue
            index = pack_dir / "_index.md"
            if not index.exists():
                continue
            meta = _parse_frontmatter(index.read_text(encoding="utf-8"))
            pack_id = meta.get("pack_id", "")
            if pack_id not in counts_by_pack:
                continue
            disease = DiseaseCode(pack_id.split("-", 1)[1])
            self._pack_scopes[disease] = PackScope(
                pack_id=pack_id,
                disease_code=disease,
                version=meta.get("version", ""),
                status=meta.get("status", ""),
                scope=_normalise_text(meta.get("scope")),
                exclusions=_normalise_text(meta.get("exclusions")),
                entries_total=counts_by_pack[pack_id],
            )

        # TY 单文件包没有独立目录，补最小 scope（通用术语，无 exclusions 概念）
        if DiseaseCode.ty not in self._pack_scopes and "KP-TY" in counts_by_pack:
            self._pack_scopes[DiseaseCode.ty] = PackScope(
                pack_id="KP-TY",
                disease_code=DiseaseCode.ty,
                version="",
                status="",
                scope="跨病种通用术语，随费用解释段按需附加",
                exclusions=None,
                entries_total=counts_by_pack["KP-TY"],
            )

    # -------------------------------------------------------------- queries

    @property
    def knowledge_version(self) -> str:
        """Version handle for Report.knowledge_version (spec 6.4)."""
        return self._knowledge_version

    @property
    def entries_total(self) -> int:
        return len(self._entries)

    @property
    def all_entries(self) -> tuple[KnowledgeEntry, ...]:
        return tuple(self._entries.values())

    def pack_scope(self, disease_code: DiseaseCode) -> PackScope:
        scope = self._pack_scopes.get(disease_code)
        if scope is None:
            raise UnknownDiseaseError(f"no knowledge pack for disease {disease_code}")
        return scope

    def entries_for(
        self,
        disease_code: DiseaseCode,
        *,
        slot: str | None = None,
        purpose: str | None = None,
    ) -> list[KnowledgeEntry]:
        scope = self.pack_scope(disease_code)
        return [
            e
            for e in self._entries.values()
            if e.pack_id == scope.pack_id
            and (slot is None or e.slot == slot)
            and (purpose is None or purpose in e.purposes)
        ]

    # ------------------------------------------------------------- assembly

    def select(
        self,
        disease_code: DiseaseCode,
        *,
        slots: tuple[str, ...] = (),
        purpose: str | None = None,
        patient_visible: bool = False,
    ) -> KnowledgeSelection:
        """Select entries for a capability; enforce the two hard gates.

        patient_visible=True moves every unapproved entry to `blocked` (audit
        trail). patient_visible=False keeps drafts and their flags available
        for internal engineering and medical review.
        """
        scope = self.pack_scope(disease_code)
        entries = self.entries_for(disease_code, purpose=purpose)
        if slots:
            entries = [e for e in entries if e.slot in slots]
        allowed: list[KnowledgeEntry] = []
        blocked: list[KnowledgeEntry] = []
        for entry in entries:
            if patient_visible and entry.status != APPROVED:
                blocked.append(entry)
                continue
            allowed.append(entry)
        return KnowledgeSelection(allowed=allowed, blocked=blocked, pack=scope)

    def check_exclusions(self, disease_code: DiseaseCode, case_text: str) -> None:
        """Raise PackExcludedError when case_text hits a pack exclusion keyword.

        v1 keeps this as an explicit keyword scan against the pack's free-text
        exclusions field; it is a safety net, not a diagnosis — exclusion hits
        always route to human review (AC 语义见 manifest §6 第 6 条).
        """
        scope = self.pack_scope(disease_code)
        if not scope.exclusions:
            return
        for keyword in _exclusion_keywords(scope.exclusions):
            if keyword and keyword in case_text:
                raise PackExcludedError(scope.pack_id, scope.exclusions)


def load_jsonl_raw(path: Path | None = None) -> list[dict]:
    """Debug helper: raw JSON dicts without contract validation."""
    target = path or DEFAULT_JSONL
    with target.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
