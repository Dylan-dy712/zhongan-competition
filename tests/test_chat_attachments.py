import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.api.app.chat_attachments import read_attachments, parse_attachment
from services.api.app.repository import AccessDenied


class ChatAttachmentTests(unittest.TestCase):
    def test_consent_is_rechecked_after_slow_ocr(self):
        conn = MagicMock()
        row = {'attachment_id': uuid4(), 'extraction': None}
        with patch('services.api.app.chat_attachments.get_attachment', side_effect=[row, AccessDenied()]), \
             patch('services.api.app.chat_attachments.parse_attachment', return_value={'status':'available','pages':[]}):
            with self.assertRaises(AccessDenied):
                read_attachments(conn, uuid4(), uuid4(), [row['attachment_id']])
        self.assertTrue(conn.commit.called, 'OCR starts after releasing the read transaction')

    def test_ocr_failure_is_explicit_and_not_cached(self):
        conn = MagicMock()
        row = {'attachment_id': uuid4(), 'name':'synthetic.png', 'media_type':'image/png', 'byte_size':20, 'extraction':None}
        with patch('services.api.app.chat_attachments.get_attachment', return_value=row), \
             patch('services.api.app.chat_attachments.require_conversation'), \
             patch('services.api.app.chat_attachments.parse_attachment', side_effect=RuntimeError('OCR_UNAVAILABLE')):
            result = read_attachments(conn, uuid4(), uuid4(), [row['attachment_id']])
        self.assertEqual(result['attachments'][0]['status'], 'unavailable')
        conn.execute.assert_not_called()

    def test_changed_attachment_bytes_are_not_read_as_the_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'attachment'
            path.write_bytes(b'changed content')
            with self.assertRaisesRegex(RuntimeError, 'ATTACHMENT_CONTENT_UNAVAILABLE'):
                parse_attachment({'storage_ref':str(path),'source_hash':'0'*64})


if __name__ == '__main__':
    unittest.main()
