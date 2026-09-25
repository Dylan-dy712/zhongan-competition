import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.repository import AccessDenied, IdempotencyConflict, create_case, request_digest
from services.api.app.contracts.core import DataOrigin


class CaseRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = MagicMock()
        self.actor_id = uuid4()
        self.subject_id = uuid4()
        self.consent_id = uuid4()
        self.kw = dict(actor_id=self.actor_id, subject_id=self.subject_id,
                       consent_id=self.consent_id, source_ref="synthetic-fixture-1",
                       external_case_ref=None, user_context=None,
                       data_origin=DataOrigin.synthetic, idempotency_key="request-1")

    def test_cross_subject_write_denied(self):
        self.conn.execute.return_value.fetchone.return_value = None
        with self.assertRaises(AccessDenied):
            create_case(self.conn, **self.kw)
        self.assertFalse(any("INSERT INTO cases" in str(c) for c in self.conn.execute.call_args_list))

    def test_missing_consent_denied(self):
        calls = [MagicMock(), MagicMock(), MagicMock()]
        calls[1].fetchone.return_value = {"?column?": 1}
        calls[2].fetchone.return_value = None
        self.conn.execute.side_effect = calls
        with self.assertRaises(AccessDenied):
            create_case(self.conn, **self.kw)

    def test_same_key_changed_payload_conflicts(self):
        calls = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        calls[1].fetchone.return_value = {"?column?": 1}
        calls[2].fetchone.return_value = {"?column?": 1}
        calls[3].fetchone.return_value = {"request_hash": "0" * 64}
        self.conn.execute.side_effect = calls
        with self.assertRaises(IdempotencyConflict):
            create_case(self.conn, **self.kw)

    def test_canonical_request_hash(self):
        self.assertEqual(request_digest({"a": 1, "b": 2}), request_digest({"b": 2, "a": 1}))


class ClosedByDefaultTests(unittest.TestCase):
    def test_unconfigured_database_returns_503(self):
        import os
        old = os.environ.pop("ZHONGAN_DATABASE_URL", None)
        try:
            response = TestClient(app).get(f"/v1/cases/{uuid4()}")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["code"], "DEPENDENCY_UNAVAILABLE")
            self.assertTrue(response.json()["trace_id"])
        finally:
            if old is not None:
                os.environ["ZHONGAN_DATABASE_URL"] = old


if __name__ == "__main__":
    unittest.main()
