"""Exercise actual PostgreSQL row/advisory locks with a synthetic release fixture."""
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier
from unittest.mock import patch

from psycopg import sql
from services.api.app import release_repository as release
from services.api.app.repository import connect, get_report
from services.api.app.review_repository import ReviewNotFound


def check_concurrency(conn, dsn, schema, *, reviewer, patient, case, consent, report, check):
    if not schema.startswith('release_test_') or conn.execute('SELECT current_schema() AS name').fetchone()['name']!=schema:
        raise ValueError('Concurrency checks require the runner disposable schema')
    def connection():
        db=connect(dsn)
        db.autocommit=True
        db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        db.execute("SET statement_timeout='15s'")
        db.execute("SET lock_timeout='10s'")
        return db

    def publish(db, key):
        return release.publish_report(db,actor_id=reviewer,case_id=case,version=1,
                                      expected_version=1,idempotency_key=key)

    def blocked(pid, holder):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if holder in conn.execute('SELECT pg_blocking_pids(%s) AS holders',(pid,)).fetchone()['holders']:
                return True
            time.sleep(.02)
        return False

    def reset():
        # Only this runner's disposable synthetic schema, before any receipts exist.
        with conn.transaction():
            conn.execute('DELETE FROM care_outbox')
            conn.execute('DELETE FROM report_releases')
            conn.execute("UPDATE reports SET status='ready' WHERE report_id=%s",(report,))
            conn.execute("UPDATE consent_purposes SET status='active' WHERE consent_id=%s",(consent,))

    with connection() as publisher, connection() as revoker, ThreadPoolExecutor(max_workers=2) as pool:
        with revoker.transaction():
            revoker.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
            attempt=pool.submit(publish,publisher,'native-revoke-first')
            check(blocked(publisher.info.backend_pid,revoker.info.backend_pid),
                  'publisher actually waits for the in-flight revocation row lock')
        try:
            attempt.result(timeout=10)
            raise AssertionError('publish survived committed revocation')
        except ReviewNotFound:
            pass
        check(conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==0,
              'revocation committing first blocks publication without a release')
        reset()

        validated,proceed=Event(),Event()
        original=release.checked_report_content
        def pause_after_validation(*args,**kwargs):
            result=original(*args,**kwargs)
            validated.set()
            if not proceed.wait(timeout=10):
                raise AssertionError('publication test coordinator timed out')
            return result
        def revoke():
            with revoker.transaction():
                revoker.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s",(consent,))
        with patch.object(release,'checked_report_content',side_effect=pause_after_validation):
            attempt=pool.submit(publish,publisher,'native-publish-first')
            try:
                check(validated.wait(timeout=5),'publication reaches validation while holding authorization locks')
                revocation=pool.submit(revoke)
                check(blocked(revoker.info.backend_pid,publisher.info.backend_pid),
                      'revocation actually waits for the publishing transaction')
            finally:
                proceed.set()
            result=attempt.result(timeout=10)
            revocation.result(timeout=10)
        check(result['report_id']==report and conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==1,
              'publication committing first persists exactly one release')
        check(get_report(conn,actor_id=patient,case_id=case,version=1,patient_view=True) is None,
              'subsequent revocation immediately hides the concurrently published report')
        reset()

        barrier=Barrier(2)
        def simultaneous(db):
            barrier.wait(timeout=5)
            return publish(db,'native-duplicate')
        first=pool.submit(simultaneous,publisher)
        second=pool.submit(simultaneous,revoker)
        results=[first.result(timeout=10),second.result(timeout=10)]
        check(results[0]==results[1] and conn.execute('SELECT count(*) AS n FROM report_releases').fetchone()['n']==1
              and conn.execute('SELECT count(*) AS n FROM care_outbox').fetchone()['n']==1,
              'simultaneous identical requests persist one release and one outbox')
        reset()
