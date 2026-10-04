"""Exercise real PostgreSQL races on the KR4 authoritative snapshot path.

Run only against the integration runner's disposable schema (same contract as
check_release_concurrency): separate autocommit connections per thread, real
row locks and unique-index races, no mocked storage.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from psycopg import sql

from services.api.app.quality_export import (
    normalized_entity_name,
    MappingCreate, attach_case_attribution, create_entity_mapping,
    draft_policy, export_quality_input, persist_snapshot,
)
from services.api.app.repository import connect

HOSPITAL_NAME = "并发映射医院"


def check_quality_concurrency(conn, dsn, schema, *, reviewer, subject, check):
    """Concurrent snapshot builds and mapping creation on a dedicated case.

    Uses its own case so the release suite's publish flow on the shared
    fixture case is not disturbed by extra documents.
    """
    def connection():
        db = connect(dsn)
        db.autocommit = True
        db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        db.execute("SET statement_timeout='15s'")
        db.execute("SET lock_timeout='10s'")
        return db

    case = uuid4()
    consent = uuid4()
    with connection() as db:
        db.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'quality-concurrency',1)",
                   (consent, subject))
        db.execute("""INSERT INTO consent_purposes(consent_id,purpose,status,granted_at)
            VALUES (%s,'case_guidance','active',now())""", (consent,))
        db.execute("""INSERT INTO cases(case_id,subject_id,consent_id,created_by,source_ref,data_origin,
            idempotency_key,request_hash) VALUES (%s,%s,%s,%s,'quality-concurrency','synthetic','qc-case',%s)""",
            (case, subject, consent, reviewer, "q" * 64))

    def seed(worker_tag):
        """One run + evidence + observed total_cost fact, attributed to the hospital."""
        run_id, evidence_id, document_id = uuid4(), uuid4(), uuid4()
        storage_ref = f"/tmp/quality-concurrency-{uuid4().hex[:8]}"
        with connection() as db:
            db.execute("""INSERT INTO documents(document_id,case_id,document_version,media_type,byte_size,
                source_hash,source_ref,storage_ref,status,policy_version)
                VALUES (%s,%s,1,'text/plain',1,%s,'quality-concurrency',%s,'parsed','test')""",
                (document_id, case, f"qc-{worker_tag}", storage_ref))
            db.execute("""INSERT INTO analysis_runs(run_id,case_id,input_hash,schema_version,pipeline_version,
                document_versions,status,current_stage,execution_mode)
                VALUES (%s,%s,%s,'0.1.0','text-parser-v1','[]','completed','validate','live')""",
                (run_id, case, f"qc-{worker_tag}"))
            db.execute("""INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,
                page_index,text_start,text_end,text_value,extraction_method,source_hash,parser_version)
                VALUES (%s,%s,%s,%s,1,0,0,5,'合成并发费用证据','synthetic',%s,'test')""",
                (evidence_id, run_id, case, document_id, f"qc-{worker_tag}"))
            db.execute("""INSERT INTO extracted_facts(fact_id,run_id,case_id,fact_type,value,raw_value,status,
                assertion,evidence_ids,extractor_version)
                VALUES (%s,%s,%s,'total_cost',jsonb_build_object('amount_minor',%s,'currency','CNY'),
                '合成并发总费用','observed','present',%s::jsonb,'quality-concurrency')""",
                (uuid4(), run_id, case, 10000 + worker_tag * 1000, json.dumps([str(evidence_id)])))
        return run_id, evidence_id, document_id

    def hospital_mapping(db, evidence_ids):
        return create_entity_mapping(db, actor_id=reviewer, body=MappingCreate(
            entity_type="hospital", display_name=HOSPITAL_NAME, evidence_ids=list(evidence_ids)))

    def build_on(db, run_id, window_end):
        policy = draft_policy(date(2026, 1, 1), window_end, min_sample_size=2, max_missing_rate=1.0)
        data, limitations = export_quality_input(db, policy=policy, dataset_version="quality-concurrency")
        if data is None:
            return None
        return persist_snapshot(db, data=data, actor_id=reviewer, limitations=limitations)

    with ThreadPoolExecutor(max_workers=4) as pool:
        # (a) 同窗口并发构建：四线程同一输入 → 同一不可变快照、仅一行、一个创建者
        run_id, evidence_id, document_a = seed(1)
        mapping = hospital_mapping(connection(), [evidence_id])
        attach_case_attribution(connection(), actor_id=reviewer, case_id=case,
            run_id=run_id, entity_id=UUID(mapping["entity_id"]), evidence_ids=[evidence_id])
        connections = [connection() for _ in range(4)]
        attempts = [pool.submit(build_on, db, run_id, date(2027, 1, 1)) for db in connections]
        results = [a.result(timeout=20) for a in attempts]
        ids = {str(r["snapshot_id"]) for r in results if r}
        created_flags = [r["created"] for r in results if r]
        check(len(ids) == 1 and None not in ids,
              "concurrent same-window builds converge on one immutable snapshot")
        check(sum(1 for flag in created_flags if flag) == 1,
              "exactly one racer reports creating the snapshot row")
        check(conn.execute("SELECT count(*) AS n FROM quality_snapshots").fetchone()["n"] == 1,
              "quality_snapshots holds exactly one row after the race")

        # (b) 不同窗口并发构建：两个互不相同的输入 → 两行、两个 id
        run_b, evidence_b, document_b = seed(2)
        attach_case_attribution(connection(), actor_id=reviewer, case_id=case,
            run_id=run_b, entity_id=UUID(mapping["entity_id"]), evidence_ids=[evidence_b])
        conns_b = [connection() for _ in range(2)]
        attempts_b = [pool.submit(build_on, db, run_b, end)
                      for db, end in zip(conns_b, (date(2027, 2, 1), date(2027, 3, 1)))]
        results_b = [a.result(timeout=20) for a in attempts_b]
        ids_b = {str(r["snapshot_id"]) for r in results_b if r}
        check(len(ids_b) == 2 and not (ids_b & ids),
              "different windows race into two distinct immutable snapshots")

        # (c) 并发同名映射创建：唯一约束竞争 → 同一实体、仅一行
        evidence_c = uuid4()
        with connection() as db:
            db.execute("""INSERT INTO evidence(evidence_id,run_id,case_id,document_id,document_version,
                page_index,text_start,text_end,text_value,extraction_method,source_hash,parser_version)
                VALUES (%s,%s,%s,%s,1,0,0,5,'并发映射证据','synthetic',%s,'test')""",
                (evidence_c, run_b, case, document_b, f"qc-c"))
        map_conns = [connection() for _ in range(4)]
        map_attempts = [pool.submit(create_entity_mapping, db, actor_id=reviewer,
            body=MappingCreate(entity_type="hospital", display_name="并发同名医院",
                               evidence_ids=[evidence_c])) for db in map_conns]
        map_results = [a.result(timeout=20) for a in map_attempts]
        entity_ids = {m["entity_id"] for m in map_results}
        created_count = sum(1 for m in map_results if m["created"])
        check(len(entity_ids) == 1 and created_count == 1,
              "concurrent identical mappings converge on one stable entity")
        stable_entity = uuid5(NAMESPACE_URL, f"quality-export-v1:entity:hospital:"
                              f"{normalized_entity_name('并发同名医院')}")
        check(entity_ids == {str(stable_entity)},
              f"raced mapping id equals the deterministic uuid5 identity (db={entity_ids}, expected={str(stable_entity)})")
