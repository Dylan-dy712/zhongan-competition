"""Create one repeatable synthetic integration identity without printing secrets."""

import hashlib
import os
import secrets
from pathlib import Path
from uuid import uuid4

import psycopg


OUTPUT = Path("/home/ubuntu/.config/zhongan/dev-fixture.env")


def ensure_reviewer(conn, env_path: Path) -> None:
    """Idempotent medical-reviewer identity for the review workbench."""
    if "ZHONGAN_REVIEWER_TOKEN" in env_path.read_text(encoding="utf-8"):
        print("Reviewer fixture already exists")
        return
    actor_id = uuid4()
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode()).hexdigest()
    conn.execute("INSERT INTO actors (actor_id, token_sha256, role) VALUES (%s, %s, 'medical_reviewer')",
                 (actor_id, digest))
    with env_path.open("a", encoding="utf-8") as env:
        env.write(f"ZHONGAN_REVIEWER_ACTOR_ID={actor_id}" + chr(10))
        env.write(f"ZHONGAN_REVIEWER_TOKEN={token}" + chr(10))
    print("Reviewer fixture created")


def main() -> None:
    if OUTPUT.exists():
        print("Synthetic fixture already exists")
        dsn = os.environ["ZHONGAN_DATABASE_URL"]
        with psycopg.connect(dsn) as conn:
            ensure_reviewer(conn, OUTPUT)
        return
    dsn = os.environ["ZHONGAN_DATABASE_URL"]
    actor_id, subject_id, consent_id = uuid4(), uuid4(), uuid4()
    token = secrets.token_urlsafe(48)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO actors (actor_id, token_sha256) VALUES (%s, %s)", (actor_id, digest))
        conn.execute(
            """INSERT INTO actor_subject_access
               (actor_id, subject_id, can_create_case, can_read_case)
               VALUES (%s, %s, true, true)""",
            (actor_id, subject_id),
        )
        conn.execute(
            """INSERT INTO consents (consent_id, subject_id, notice_version, version)
               VALUES (%s, %s, 'synthetic-dev-v1', 1)""",
            (consent_id, subject_id),
        )
        conn.execute(
            """INSERT INTO consent_purposes
               (consent_id, purpose, status, granted_at)
               VALUES (%s, 'case_guidance', 'active', now())""",
            (consent_id,),
        )
    old_umask = os.umask(0o077)
    try:
        OUTPUT.write_text(
            f"ZHONGAN_DEV_SUBJECT_ID={subject_id}\n"
            f"ZHONGAN_DEV_CONSENT_ID={consent_id}\n"
            f"ZHONGAN_DEV_BEARER_TOKEN={token}\n",
            encoding="utf-8",
        )
    finally:
        os.umask(old_umask)
    print("Synthetic fixture created; credentials stored with mode 600")


if __name__ == "__main__":
    main()
