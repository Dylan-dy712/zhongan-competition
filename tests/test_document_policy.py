import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from services.api.app.main import ChatMessage, validate_file_signature


class DocumentPolicyTests(unittest.TestCase):
    def test_analysis_accepts_more_than_twenty_documents(self):
        ids = [uuid4() for _ in range(100)]
        body = ChatMessage(request_id=uuid4(), message='Synthetic material analysis', document_ids=ids)
        self.assertEqual(body.document_ids, ids)
        self.assertNotIn('maxItems', ChatMessage.model_json_schema()['properties']['document_ids'])

    def check(self, content: bytes, media_type: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            path.write_bytes(content)
            validate_file_signature(path, media_type)

    def test_pdf_signature(self):
        self.check(b"%PDF-1.7\nsynthetic", "application/pdf")

    def test_declared_pdf_rejects_other_content(self):
        with self.assertRaises(HTTPException) as caught:
            self.check(b"not-pdf", "application/pdf")
        self.assertEqual(caught.exception.status_code, 415)

    def test_controlled_text_requires_utf8(self):
        with self.assertRaises(HTTPException) as caught:
            self.check(b"\xff\xfe", "text/plain")
        self.assertEqual(caught.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()
