"""Synthetic PDFs only: page identity, actual text geometry, and authorization."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from services.api.app import main as api
from services.api.app.contracts.core import Evidence, TextSpan
from services.api.app.document_preview import render_evidence_page,ocr_regions


def synthetic_pdf(path, rotation=0, crop=False):
    writer = PdfWriter()
    for text in ('UNRELATED FIRST PAGE', 'FOLLOW UP IN TWO WEEKS'):
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data((f'BT /F1 18 Tf 72 650 Td ({text}) Tj '
                         '0 -45 Td (Synthetic document for preview testing only.) Tj ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
        if crop:
            page.cropbox.lower_left = (30, 40)
            page.cropbox.upper_right = (570, 760)
        if rotation:
            page.rotate(rotation)
    with path.open('wb') as output:
        writer.write(output)


class PdfPagePreviewTests(unittest.TestCase):
    def test_scanned_page_excerpt_uses_exact_ocr_regions_and_excludes_unreadable_lines(self):
        blocks=[{'text_content':'合成第一行原文','bbox':[.1,.1,.8,.2],'metadata':{}},
                {'text_content':'合成第二行原文','bbox':[.1,.3,.8,.4],'metadata':{}},
                {'text_content':'模糊不可读文字','bbox':[.1,.5,.8,.6],'metadata':{'needs_clearer_photo':True}},
                {'text_content':'模型页面转录','bbox':[0,0,1,1],'metadata':{'coordinate_precision':'page'}}]
        self.assertEqual(ocr_regions('合成第一行原文\n合成第二行原文',blocks),[blocks[0]['bbox'],blocks[1]['bbox']])
        self.assertEqual(ocr_regions('合成第二行原文',blocks),[blocks[1]['bbox']])
        self.assertEqual(ocr_regions('不存在的引用以及模糊不可读文字',blocks),[])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'synthetic.pdf'
        synthetic_pdf(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def assert_regions_cover_ink(self, data, regions):
        self.assertTrue(regions)
        with Image.open(io.BytesIO(data)) as image:
            self.assertLessEqual(max(image.size), 2000)
            for box in regions:
                self.assertTrue(0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)
                crop = image.crop((int(box[0]*image.width), int(box[1]*image.height),
                                   int(box[2]*image.width), int(box[3]*image.height))).convert('L')
                self.assertLess(crop.getextrema()[0], 80, 'Highlight must overlap the actual rendered text')

    def test_selects_second_page_and_matches_whitespace_without_wrong_page_fallback(self):
        data, regions = render_evidence_page(self.path, 1, quote='FOLLOW UP\nIN TWO WEEKS')
        self.assertTrue(data.startswith(b'\x89PNG'))
        self.assert_regions_cover_ink(data, regions)
        self.assertAlmostEqual(regions[0][0], 72/600, delta=.01)
        self.assertTrue(.15 < regions[0][1] < .2)
        _, wrong_page = render_evidence_page(self.path, 0, quote='FOLLOW UP IN TWO WEEKS')
        self.assertEqual(wrong_page, [], 'Never mark unrelated text when the quote is absent')

    def test_rotation_and_crop_coordinates_match_rendered_page(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                synthetic_pdf(self.path, rotation=rotation, crop=True)
                data, regions = render_evidence_page(self.path, 1, quote='FOLLOW UP IN TWO WEEKS')
                self.assert_regions_cover_ink(data, regions)

    def test_existing_native_parser_evidence_can_be_located_without_reanalysis(self):
        from services.api.app.worker import parse_pdf, evidence_for_page
        pages = parse_pdf(self.path)
        document = {'document_id': uuid4(), 'document_version': 2}
        evidence = evidence_for_page(document, pages[1])[0]
        self.assertIsNone(evidence['bbox'], 'Existing native PDF evidence has no stored geometry')
        data, regions = render_evidence_page(self.path, evidence['page_index'], quote=evidence['text'])
        self.assertEqual(len(regions), 2, 'Both lines of the existing evidence excerpt must be located')
        self.assert_regions_cover_ink(data, regions)

    def test_scanned_pdf_uses_original_normalized_ocr_box(self):
        with Image.new('RGB', (600, 800), 'white') as image:
            ImageDraw.Draw(image).rectangle((60, 160, 300, 220), fill='black')
            image.save(self.path, 'PDF', resolution=72)
        box = (.1, .2, .5, .275)
        data, regions = render_evidence_page(self.path, 0, quote='OCR text', bbox=box)
        self.assertEqual(regions, [list(box)])
        self.assert_regions_cover_ink(data, regions)

    def test_unlocatable_excerpt_still_has_page_image_and_no_invented_box(self):
        data, regions = render_evidence_page(self.path, 1, quote='This is not in this PDF')
        self.assertTrue(data.startswith(b'\x89PNG'))
        self.assertEqual(regions, [])
        for index in (-1, 2):
            with self.assertRaises(IndexError):
                render_evidence_page(self.path, index)


class PdfPagePreviewApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / 'synthetic.pdf'
        synthetic_pdf(self.path)
        self.actor = uuid4()
        self.item = Evidence(evidence_id=uuid4(), case_id=uuid4(), document_id=uuid4(),
            document_version=2, page_index=1, media_type='application/pdf', source_name='synthetic.pdf',
            text_span=TextSpan(start=0, end=22, text='FOLLOW UP IN TWO WEEKS'),
            extraction_method='native_text', source_hash='a'*64, parser_version='synthetic')
        self.previous = api.app.dependency_overrides.copy()
        api.app.dependency_overrides[api.current_actor] = lambda: self.actor
        api.app.dependency_overrides[api.database] = lambda: object()
        api.app.dependency_overrides[api.document_storage_root] = lambda: self.root
        self.client = TestClient(api.app)
        self.url = f'/v1/evidence/{self.item.evidence_id}/page-image'

    def tearDown(self):
        self.client.close()
        api.app.dependency_overrides.clear()
        api.app.dependency_overrides.update(self.previous)
        self.directory.cleanup()

    def document(self):
        from types import SimpleNamespace
        return SimpleNamespace(media_type='application/pdf'), str(self.path)

    def test_exact_evidence_document_version_and_page_are_served_privately(self):
        with patch.object(api, 'get_evidence', return_value=self.item) as evidence, \
             patch.object(api, 'get_document', return_value=self.document()) as document:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertTrue(response.headers['content-type'].startswith('image/png'))
        self.assertEqual(response.headers['cache-control'], 'private, no-store')
        self.assertTrue(json.loads(response.headers['x-evidence-regions']))
        self.assertEqual(evidence.call_args.kwargs['actor_id'], self.actor)
        self.assertEqual(document.call_args.kwargs, dict(actor_id=self.actor, case_id=self.item.case_id,
            document_id=self.item.document_id, version=2))

    def test_image_page_level_reference_loads_original_with_stored_ocr_highlights(self):
        from types import SimpleNamespace
        photo=self.root/'synthetic.png'
        Image.new('RGB',(500,700),'white').save(photo)
        self.item.media_type='image/png';self.item.page_index=0;self.item.bbox=None
        boxes=[[.1,.2,.8,.3]]
        with patch.object(api,'get_evidence',return_value=self.item),patch.object(api,'get_document',return_value=(SimpleNamespace(media_type='image/png'),str(photo))),patch.object(api,'evidence_ocr_regions',return_value=boxes) as locate:
            response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(response.headers['x-evidence-regions']),boxes)
        locate.assert_called_once_with(unittest.mock.ANY,self.item.evidence_id,self.item.text_span.text)

    def test_unauthorized_evidence_or_revoked_document_never_renders(self):
        with patch.object(api, 'get_evidence', return_value=None), \
             patch.object(api, 'get_document') as document, patch.object(api, 'render_evidence_page') as render:
            self.assertEqual(self.client.get(self.url).status_code, 404)
            document.assert_not_called()
            render.assert_not_called()
        with patch.object(api, 'get_evidence', return_value=self.item), \
             patch.object(api, 'get_document', return_value=None), patch.object(api, 'render_evidence_page') as render:
            self.assertEqual(self.client.get(self.url).status_code, 404)
            render.assert_not_called()

    def test_storage_escape_missing_page_and_unreadable_pdf(self):
        with patch.object(api, 'get_evidence', return_value=self.item), \
             patch.object(api, 'get_document', return_value=(self.document()[0], str(self.root.parent/'escape.pdf'))), \
             patch.object(api, 'render_evidence_page') as render:
            self.assertEqual(self.client.get(self.url).status_code, 503)
            render.assert_not_called()
        with patch.object(api, 'get_evidence', return_value=self.item), \
             patch.object(api, 'get_document', return_value=self.document()):
            self.item.page_index = 99
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.item.page_index = 1
            self.path.write_bytes(b'broken PDF')
            result = self.client.get(self.url)
            self.assertEqual(result.status_code, 503)
            self.assertNotIn(str(self.root), result.text)


if __name__ == '__main__':
    unittest.main()
