"""PostgreSQL review queue and immutable decision writes for REQ-06."""

import json
from uuid import UUID, uuid4

from .contracts.core import Insight, ReviewCorrection, ReviewDecision, ReviewTask
from .review_service import corrected_insight_payload


class ReviewAccessDenied(Exception): pass
class ReviewNotFound(Exception): pass
class StaleReview(Exception): pass


def _insight(row) -> Insight:
    return Insight(
        insight_id=row["insight_id"], case_id=row["case_id"], run_id=row["run_id"],
        category=row["category"], label=row["label"], severity=row["severity"],
        confidence=row["confidence"], confidence_method=row["confidence_method"],
        evidence_ids=row["evidence_ids"], rationale=row["rationale"],
        uncertainty=row["uncertainty"], suggested_action=row["suggested_action"],
        review_required=row["review_required"], review_status=row["review_status"],
        judgment_status=row["judgment_status"], rule_version=row["rule_version"],
        knowledge_refs=row["knowledge_refs"],
    )


def list_reviews(conn, *, actor_id: UUID, status: str, limit: int,
                 cursor: UUID | None = None) -> list[ReviewTask]:
    role = conn.execute("SELECT role FROM actors WHERE actor_id=%s AND active=true", (actor_id,)).fetchone()
    if not role or role["role"] != "medical_reviewer":
        raise ReviewAccessDenied()
    rows = conn.execute(
        """SELECT t.*,i.* FROM review_tasks t JOIN insights i ON i.insight_id=t.target_id
           JOIN cases c ON c.case_id=t.case_id
           JOIN actor_subject_access a ON a.subject_id=c.subject_id
             AND a.actor_id=%s AND a.can_read_case=true
           JOIN actors ac ON ac.actor_id=a.actor_id AND ac.active=true AND ac.role='medical_reviewer'
           JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
           JOIN consent_purposes p ON p.consent_id=co.consent_id
             AND p.purpose='case_guidance' AND p.status='active'
             AND (p.expires_at IS NULL OR p.expires_at>now())
           WHERE t.status=%s AND (%s::uuid IS NULL OR t.review_id>%s::uuid)
           ORDER BY t.review_id LIMIT %s""", (actor_id, status, cursor, cursor, limit),
    ).fetchall()
    return [ReviewTask(review_id=r["review_id"], case_id=r["case_id"], run_id=r["run_id"],
        target_type=r["target_type"], target_id=r["target_id"],
        target_version=r["target_version"], status=r["status"], reason=r["reason"],
        target=_insight(r), created_at=r["created_at"]) for r in rows]


def decide_review(conn, *, actor_id: UUID, review_id: UUID, expected_version: int,
                  decision: str, reason: str, corrections: list[ReviewCorrection]) -> ReviewDecision:
    with conn.transaction():
        row = conn.execute(
            """SELECT t.*,i.*,ac.role AS actor_role FROM review_tasks t
               JOIN insights i ON i.insight_id=t.target_id JOIN cases c ON c.case_id=t.case_id
               JOIN actor_subject_access a ON a.subject_id=c.subject_id
                 AND a.actor_id=%s AND a.can_read_case=true
               JOIN actors ac ON ac.actor_id=a.actor_id AND ac.active=true
               JOIN consents co ON co.consent_id=c.consent_id AND co.subject_id=c.subject_id
               JOIN consent_purposes p ON p.consent_id=co.consent_id
                 AND p.purpose='case_guidance' AND p.status='active'
                 AND (p.expires_at IS NULL OR p.expires_at>now())
               WHERE t.review_id=%s FOR UPDATE OF t,i FOR SHARE OF ac,a,c,co,p""", (actor_id, review_id),
        ).fetchone()
        if not row:
            raise ReviewNotFound()
        if row["actor_role"] != "medical_reviewer":
            raise ReviewAccessDenied()
        latest = conn.execute(
            "SELECT version,payload FROM insight_revisions WHERE insight_id=%s ORDER BY version DESC LIMIT 1",
            (row["target_id"],),
        ).fetchone()
        current_version = latest["version"] if latest else 1
        if row["status"] != "pending" or expected_version != current_version:
            raise StaleReview()
        if decision != "correct" and corrections:
            raise ValueError("corrections only allowed for correct decision")
        if decision == "correct":
            current = Insight.model_validate(latest["payload"]) if latest else _insight(row)
            evidence = conn.execute(
                "SELECT evidence_id FROM evidence WHERE case_id=%s AND run_id=%s",
                (row["case_id"], row["run_id"]),
            ).fetchall()
            payload = corrected_insight_payload(current, corrections,
                                                {str(x["evidence_id"]) for x in evidence})
            conn.execute(
                "INSERT INTO insight_revisions (insight_id,version,payload,review_id) VALUES (%s,%s,%s::jsonb,%s)",
                (row["target_id"], current_version + 1, json.dumps(payload, ensure_ascii=False), review_id),
            )
            review_status = "corrected"
        else:
            review_status = "approved" if decision == "approve" else "rejected"
        conn.execute("UPDATE insights SET review_status=%s,review_required=false WHERE insight_id=%s",
                     (review_status, row["target_id"]))
        conn.execute("UPDATE review_tasks SET status='decided',decided_at=now() WHERE review_id=%s", (review_id,))
        decision_id = uuid4()
        result = conn.execute(
            """INSERT INTO review_decisions
               (decision_id,review_id,target_type,target_id,target_version,decision,reason,
                corrections,reviewer_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
               RETURNING decided_at""",
            (decision_id, review_id, row["target_type"], row["target_id"], current_version,
             decision, reason, json.dumps([c.model_dump(mode="json") for c in corrections], ensure_ascii=False), actor_id),
        ).fetchone()
    return ReviewDecision(decision_id=decision_id, review_id=review_id,
        target_type=row["target_type"], target_id=row["target_id"], target_version=current_version,
        decision=decision, reason=reason, corrections=corrections,
        reviewer_id=actor_id, decided_at=result["decided_at"])
