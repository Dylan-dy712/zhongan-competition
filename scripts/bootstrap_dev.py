"""Create one synthetic-only development actor and purpose grant.

Run only against an isolated local development database after 001_cases.sql.
The high-entropy API token is shown once and is never written to this repository.
"""

import hashlib
import os
import secrets
from uuid import uuid4

import psycopg


def main() -> None:
    dsn = os.getenv("ZHONGAN_DATABASE_URL")
    if not dsn:
        raise SystemExit("ZHONGAN_DATABASE_URL is not set")
    actor_id, subject_id, consent_id = uuid4(), uuid4(), uuid4()
    token = secrets.token_urlsafe(48)
    token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            conn.execute("INSERT INTO actors (actor_id, token_sha256) VALUES (%s, %s)", (actor_id, token_sha256))
            conn.execute(
                """INSERT INTO actor_subject_access
                   (actor_id, subject_id, can_create_case, can_read_case)
                   VALUES (%s, %s, true, true)""",
                (actor_id, subject_id),
            )
            conn.execute(
                """INSERT INTO consents (consent_id, subject_id, notice_version, version)
                   VALUES (%s, %s, %s, 1)""",
                (consent_id, subject_id, "synthetic-dev-v1"),
            )
            conn.execute(
                """INSERT INTO consent_purposes
                   (consent_id, purpose, status, granted_at)
                   VALUES (%s, 'case_guidance', 'active', now())""",
                (consent_id,),
            )
    print("Synthetic development credentials (shown once; do not commit):")
    print(f"actor_id={actor_id}")
    print(f"subject_id={subject_id}")
    print(f"consent_id={consent_id}")
    print(f"bearer_token={token}")


if __name__ == "__main__":
    main()
