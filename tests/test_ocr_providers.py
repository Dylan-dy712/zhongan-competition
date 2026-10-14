import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import requests

from services.api.app.ocr import create_ocr, page_ocr_method
from services.api.app.tencent_ocr import OCR_METHOD, OCR_VERSION
from services.api.app.volcengine_ocr import VolcengineOcr, normalize_response, signed_headers
from services.api.app.worker import evidence_for_page, ocr_page, worker_error_code


class OcrProviderTests(unittest.TestCase):
    def config(self):
        return patch.dict(os.environ, {'VOLCENGINE_OCR_ACCESS_KEY_ID': 'synthetic-ak',
                                      'VOLCENGINE_OCR_SECRET_ACCESS_KEY': 'synthetic-sk'}, clear=True)

    def payload(self):
        return {'code': 10000, 'request_id': 'synthetic-request', 'data': {
            'line_texts': ['医疗发票', '', '金额123.00元', '合成材料结束'],
            'line_rects': [{'x': 10, 'y': 20, 'width': 80, 'height': 40}]*4,
            'line_probs': [.99, .99, .4, .99]}}

    def test_switch_is_explicit_and_missing_credentials_never_use_tencent(self):
        with patch.dict(os.environ, {'ZHONGAN_OCR_PROVIDER': 'volcengine',
                                    'TENCENTCLOUD_SECRET_ID': 'synthetic', 'TENCENTCLOUD_SECRET_KEY': 'synthetic'}, clear=True), \
             patch('services.api.app.ocr.TencentOcr') as tencent:
            with self.assertRaisesRegex(RuntimeError, '^OCR_NOT_CONFIGURED$'):
                create_ocr()
            tencent.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), patch('services.api.app.ocr.TencentOcr') as tencent:
            create_ocr()
            tencent.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, '^OCR_PROVIDER_NOT_SUPPORTED$'):
            create_ocr('unrecognized')

    def test_low_confidence_amount_is_preserved_for_audit_and_excluded_from_evidence(self):
        response = normalize_response(self.payload(), 100, 100)
        self.assertEqual(response['blocks'][0]['bbox'], [.1, .2, .9, .6])
        self.assertEqual([b['order'] for b in response['blocks']], [0, 1, 2])
        ocr = Mock(method=VolcengineOcr.method, version=VolcengineOcr.version)
        ocr.recognize.return_value = response
        page = ocr_page(b'synthetic', 100, 100, {'metadata': {}, 'page_index': 0}, ocr)
        self.assertEqual(page['parser_version'], VolcengineOcr.version)
        self.assertEqual(page_ocr_method(page), VolcengineOcr.method)
        self.assertEqual(page['text'], '医疗发票\n合成材料结束')
        self.assertEqual(page['blocks'][1]['text'], '金额123.00元')
        evidence = evidence_for_page({'document_id': 'synthetic', 'document_version': 1}, page)
        self.assertEqual([e['text'] for e in evidence], ['医疗发票', '合成材料结束'])
        for item in evidence:
            self.assertEqual(page['text'][item['start']:item['end']], item['text'])
            self.assertEqual(item['bbox'], [.1, .2, .9, .6])
        self.assertEqual(page_ocr_method({'parser_version': OCR_VERSION}), OCR_METHOD)
        self.assertIsNone(page_ocr_method({'parser_version': 'controlled-text-v1'}))

    def test_missing_confidence_is_unknown_and_malformed_text_is_rejected(self):
        payload = self.payload()
        payload['data'].pop('line_probs')
        self.assertIsNone(normalize_response(payload, 100, 100)['blocks'][0]['metadata']['confidence_score'])
        payload['data']['line_texts'] = [123]
        with self.assertRaisesRegex(RuntimeError, 'INVALID_RESPONSE'):
            normalize_response(payload, 100, 100)

    def test_http_call_uses_signed_form_without_remote_filtering_or_redirects(self):
        response = Mock(status_code=200)
        response.json.return_value = self.payload()
        with self.config(), patch('services.api.app.volcengine_ocr.requests.post', return_value=response) as post:
            VolcengineOcr().recognize(b'synthetic', 100, 100)
        _, kwargs = post.call_args
        self.assertEqual(parse_qs(kwargs['data'].decode())['filter_thresh'], ['0'])
        self.assertFalse(kwargs['allow_redirects'])
        self.assertIn('/cn-north-1/cv/request', kwargs['headers']['Authorization'])
        self.assertEqual(post.call_count, 1)

    def test_provider_errors_are_bounded_and_requests_are_not_retried(self):
        for status, payload, expected in [
            (403, {'ResponseMetadata': {'Error': {'Code': 'AccessDenied', 'Message': 'private content'}}}, 'AccessDenied'),
            (200, {'code': 50400, 'message': 'private content'}, '50400'),
            (403, {'code': 'contains sensitive text'}, 'HTTP_403'),
            (200, {}, 'HTTP_200'),
        ]:
            with self.subTest(expected=expected):
                response = Mock(status_code=status)
                response.json.return_value = payload
                with self.config(), patch('services.api.app.volcengine_ocr.requests.post', return_value=response) as post:
                    with self.assertRaisesRegex(RuntimeError, 'OCR_PROVIDER_ERROR:'+expected+'$'):
                        VolcengineOcr().recognize(b'synthetic', 100, 100)
                    self.assertEqual(post.call_count, 1)
        with self.config(), patch('services.api.app.volcengine_ocr.requests.post', side_effect=requests.Timeout('private content')) as post:
            with self.assertRaisesRegex(RuntimeError, 'OCR_PROVIDER_ERROR:TIMEOUT$'):
                VolcengineOcr().recognize(b'synthetic', 100, 100)
            self.assertEqual(post.call_count, 1)

    def test_oversize_input_is_rejected_before_network_call(self):
        with self.config(), patch('services.api.app.volcengine_ocr.requests.post') as post:
            with self.assertRaisesRegex(RuntimeError, 'IMAGE_TOO_LARGE'):
                VolcengineOcr().recognize(b'x'*(6*1024*1024+1), 100, 100)
            post.assert_not_called()

    def test_temporary_credentials_are_signed_and_provider_errors_survive_worker(self):
        headers = signed_headers(b'synthetic', 'synthetic-ak', 'synthetic-sk', 'synthetic-token', '20261014T010203Z')
        self.assertEqual(headers['X-Security-Token'], 'synthetic-token')
        self.assertIn('x-security-token', headers['Authorization'])
        code = 'OCR_PROVIDER_ERROR:ResourceUnavailable.ResourcePackageRunOut'
        self.assertEqual(worker_error_code(RuntimeError(code)), code)
        self.assertEqual(worker_error_code(RuntimeError('OCR_PROVIDER_ERROR:private data here')), 'PARSE_FAILED')


if __name__ == '__main__':
    unittest.main()
