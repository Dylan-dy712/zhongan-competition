"""Authoritative quality-profile export from the business database.

Honesty boundaries of this module (spec REQ-08; do not widen without new
authoritative sources):
- Only cost_level is exported today, from observed total_cost facts bound to
  reviewer-mapped hospital entities. Rule audits, readmission followup and
  question-versioned feedback have no authoritative source in the business
  database yet and are left absent instead of being invented.
- The cohort observation date is the analysis-run creation date, because no
  structured discharge date exists; every snapshot carries this proxy as an
  explicit limitation.
- Entity identity exists only through reviewer-mapped entity_mappings rows,
  each backed by at least one evidence id inside the attributed run.
"""
import hashlib
import json
import re
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid5

from .contracts.knowledge import DiseaseCode
from .contracts.core import Contract
from .quality_profiles import (
    Attribution, CohortRecord, MetricPolicy, NumberSource, QualityEntity,
    QualityInput, build_profiles,
)
from .review_repository import ReviewAccessDenied

EXPORT_VERSION = 'quality-export-v1'
_PLACEHOLDER_RULE_VERSION = 'not-audited'
_UNMAPPED_TREATMENT = 'unmapped'


class MappingCreate(Contract):
    entity_type: str
    display_name: str
    evidence_ids: list[UUID]


class SnapshotBuild(Contract):
    window_start: date
    window_end: date
    dataset_version: str | None = None
    min_sample_size: int = 5
    max_missing_rate: float = 0.2


def normalized_entity_name(name: str) -> str:
    return re.sub(r"\s+", "", name).casefold()


def entity_uuid(entity_type: str, display_name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{EXPORT_VERSION}:entity:{entity_type}:{normalized_entity_name(display_name)}")


def require_reviewer(conn, actor_id: UUID) -> None:
    row = conn.execute("SELECT role FROM actors WHERE actor_id=%s AND active=true", (actor_id,)).fetchone()
    if not row or row["role"] != "medical_reviewer":
        raise ReviewAccessDenied()


def _evidence_owned(conn, actor_id: UUID, evidence_ids: list[UUID]) -> bool:
    return conn.execute(
        """SELECT count(*) AS n FROM evidence e JOIN cases c ON c.case_id=e.case_id
           JOIN actor_subject_access a ON a.subject_id=c.subject_id AND a.actor_id=%s AND a.can_read_case=true
           WHERE e.evidence_id=ANY(%s)""",
        (actor_id, [str(e) for e in evidence_ids]),
    ).fetchone()["n"] == len(evidence_ids)


def create_entity_mapping(conn, *, actor_id: UUID, body: MappingCreate) -> dict:
    require_reviewer(conn, actor_id)
    if not body.evidence_ids or not _evidence_owned(conn, actor_id, body.evidence_ids):
        raise ValueError("mapping requires evidence ids inside your authorized cases")
    entity_id = entity_uuid(body.entity_type, body.display_name)
    row = conn.execute(
        """INSERT INTO entity_mappings (entity_id,entity_type,display_name,normalized_name,
               source_evidence_ids,created_by)
           VALUES (%s,%s,%s,%s,%s::jsonb,%s)
           ON CONFLICT (entity_type, normalized_name) DO NOTHING RETURNING entity_id""",
        (str(entity_id), body.entity_type, body.display_name.strip(),
         normalized_entity_name(body.display_name), json.dumps([str(e) for e in body.evidence_ids]),
         actor_id),
    ).fetchone()
    created = row is not None
    if not created:
        row = conn.execute("SELECT entity_id FROM entity_mappings WHERE entity_id=%s", (str(entity_id),)).fetchone()
    return {"entity_id": str(row["entity_id"]), "created": created,
            "normalized_name": normalized_entity_name(body.display_name)}


def list_entity_mappings(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT entity_id,entity_type,display_name,created_at FROM entity_mappings ORDER BY created_at").fetchall()]


def attach_case_attribution(conn, *, actor_id: UUID, case_id: UUID, run_id: UUID,
                            entity_id: UUID, evidence_ids: list[UUID]) -> dict:
    require_reviewer(conn, actor_id)
    if not evidence_ids or not _evidence_owned(conn, actor_id, evidence_ids):
        raise ValueError("attribution requires evidence ids inside your authorized cases")
    if not conn.execute("SELECT 1 FROM entity_mappings WHERE entity_id=%s", (str(entity_id),)).fetchone():
        raise ValueError("unknown entity mapping")
    if not conn.execute("SELECT 1 FROM analysis_runs WHERE run_id=%s AND case_id=%s", (str(run_id), str(case_id))).fetchone():
        raise ValueError("run is outside the given case")
    conn.execute(
        """INSERT INTO case_entity_attribution (case_id,run_id,entity_id,evidence_ids,created_by)
           VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT (run_id, entity_id) DO NOTHING""",
        (str(case_id), str(run_id), str(entity_id), json.dumps([str(e) for e in evidence_ids]), actor_id),
    )
    return {"attached": True}


def draft_policy(window_start: date, window_end: date, *, min_sample_size: int, max_missing_rate: float) -> MetricPolicy:
    """Draft policy: comparison stays rejected until a reviewer freezes it."""
    return MetricPolicy(version=f"draft:{window_start.isoformat()}:{window_end.isoformat()}", status="draft",
        window_start=window_start, window_end=window_end, min_sample_size=min_sample_size,
        max_missing_rate=max_missing_rate, readmission_window_days=90,
        medication_rule_version=_PLACEHOLDER_RULE_VERSION, treatment_rule_version=_PLACEHOLDER_RULE_VERSION,
        guidance_rule_version=_PLACEHOLDER_RULE_VERSION, feedback_question_version=_PLACEHOLDER_RULE_VERSION)


def assemble_records(rows: list[dict]) -> tuple[list[QualityEntity], list[CohortRecord], list[str]]:
    """Pure assembly from exported row dicts; rows missing an observed total are dropped."""
    entities: dict[str, QualityEntity] = {}
    records: list[CohortRecord] = []
    limitations: list[str] = []
    for row in rows:
        if row.get("total_minor") is None:
            continue
        refs = [str(r) for r in row.get("evidence_ids", []) if r]
        if not refs:
            continue  # no source, no record: an unbound cost never enters the cohort
        entity_id = row["entity_id"]
        if entity_id not in entities:
            entities[entity_id] = QualityEntity(entity_id=entity_id, entity_type="hospital",
                display_name=row["display_name"])
        record = CohortRecord(encounter_id=UUID(row["encounter_id"]), subject_ref=row["subject_ref"],
            hospital_id=entity_id, discharged_at=row["observed_date"], disease_group=DiseaseCode.ty,
            treatment_group=_UNMAPPED_TREATMENT,
            attributions=[Attribution(entity_id=entity_id, entity_type="hospital",
                metrics=["cost_level"], source_refs=[UUID(r) for r in refs[:1]])],
            total_cost_minor=NumberSource(value=int(row["total_minor"]), source_refs=[UUID(r) for r in refs]))
        records.append(record)
    if records:
        limitations.append("就医日期以分析完成日期为代理（业务库暂无结构化出院日期）")
        limitations.append("病种分组暂以通用组占位；治疗/风险/医保分层未映射，比较保持拒绝")
        limitations.append("仅导出费用水平维度：规则审计、再入院随访与版本化问卷反馈暂无权威来源")
    return list(entities.values()), records, limitations


def _subject_pseudonym(subject_id) -> str:
    return hashlib.sha256(str(subject_id).encode()).hexdigest()[:16]


def export_quality_input(conn, *, policy: MetricPolicy, dataset_version: str) -> tuple[QualityInput | None, list[str]]:
    rows = conn.execute(
        """SELECT a.case_id, a.run_id, m.entity_id, m.display_name, a.evidence_ids,
                  ef.value->>'amount_minor' AS total_minor, ef.evidence_ids AS fact_evidence,
                  c.subject_id, c.data_origin, r.created_at
           FROM case_entity_attribution a
           JOIN entity_mappings m ON m.entity_id=a.entity_id AND m.entity_type='hospital'
           JOIN analysis_runs r ON r.run_id=a.run_id
           JOIN cases c ON c.case_id=a.case_id
           JOIN extracted_facts ef ON ef.run_id=a.run_id AND ef.fact_type='total_cost' AND ef.status='observed'
           WHERE r.created_at::date BETWEEN %s AND %s
           ORDER BY a.run_id""", (policy.window_start, policy.window_end)).fetchall()
    if not rows:
        return None, ["映射窗口内没有绑定到机构且费用已核实的记录"]
    origins = {r["data_origin"] for r in rows}
    if len(origins) > 1:
        raise ValueError("mixed data origins inside the export window")
    assembled = []
    for r in rows:
        refs = [str(e) for e in (r["fact_evidence"] or [])] + [str(e) for e in (r["evidence_ids"] or [])]
        assembled.append({
            "entity_id": str(r["entity_id"]), "display_name": r["display_name"],
            "encounter_id": str(uuid5(r["run_id"], "encounter:primary")),
            "subject_ref": _subject_pseudonym(r["subject_id"]),
            "observed_date": r["created_at"].date(),
            "total_minor": int(r["total_minor"]) if r["total_minor"] is not None else None,
            "evidence_ids": list(dict.fromkeys(refs)),
        })
    entities, records, limitations = assemble_records(assembled)
    if not records:
        return None, limitations
    data = QualityInput(dataset_version=dataset_version, data_origin=origins.pop(),
                        entities=entities, records=records, policy=policy)
    return data, limitations


def persist_snapshot(conn, *, data: QualityInput, actor_id: UUID, limitations: list[str]) -> dict:
    snapshot = build_profiles(data)
    existing = conn.execute("SELECT 1 FROM quality_snapshots WHERE manifest_hash=%s",
                            (snapshot["input_sha256"],)).fetchone()
    conn.execute(
        """INSERT INTO quality_snapshots (snapshot_id,dataset_version,data_origin,policy,
               manifest_hash,limitations,payload,created_by)
           VALUES (%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s)
           ON CONFLICT (manifest_hash) DO NOTHING""",
        (snapshot["snapshot_id"], data.dataset_version, data.data_origin,
         json.dumps(snapshot["policy"]), snapshot["input_sha256"],
         json.dumps(limitations), json.dumps(snapshot), actor_id),
    )
    row = conn.execute(
        """SELECT snapshot_id,created_at FROM quality_snapshots WHERE manifest_hash=%s""",
        (snapshot["input_sha256"],)).fetchone()
    return {**snapshot, "row_created_at": row["created_at"].isoformat(), "created": existing is None}


def list_snapshots(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT snapshot_id,dataset_version,data_origin,created_at,
                  jsonb_array_length(payload->'profiles') AS profile_count
           FROM quality_snapshots ORDER BY created_at DESC""").fetchall()]


def load_snapshot(conn, snapshot_id: UUID) -> dict | None:
    row = conn.execute(
        "SELECT payload,limitations FROM quality_snapshots WHERE snapshot_id=%s", (str(snapshot_id),)).fetchone()
    if not row:
        return None
    return {**row["payload"], "limitations": row["limitations"]}
