import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError
from services.api.app.document_fields import DocumentPrediction, original_quote, parse_prediction
from scripts.preliminary_kr1 import atoms, layout_text, mapping, normalize, repair_name, score, write


class PreliminaryKR1Tests(unittest.TestCase):
    def test_layout_restores_rows_without_labels(self):
        cache = {'text': '药A\n药B\n12\n24', 'lines': [
            {'text':'药A','bbox':[.1,.1,.2,.12]}, {'text':'药B','bbox':[.1,.2,.2,.22]},
            {'text':'12','bbox':[.7,.1,.8,.12]}, {'text':'24','bbox':[.7,.2,.8,.22]}]}
        self.assertEqual(layout_text(cache), '药A | 12\n药B | 24')
    def test_money_multiset_and_inferred_categories(self):
        self.assertEqual(normalize(1.20), normalize('1.2'))
        self.assertEqual(normalize('检查（CT）'), normalize('检查(CT)'))
        self.assertNotEqual(normalize('疑似肺炎'), normalize('肺炎'))
        fields = {'blocks': [{'costDetailList': [
            {'detailName': '药A', 'feeAmount': 12, 'itemCategoryName': '药费', 'category_inferred': True},
            {'detailName': '药A', 'feeAmount': 12, 'itemCategoryName': '药费', 'category_inferred': False}]}]}
        result = atoms(fields)
        self.assertEqual(sum(result['cost_detail_name_amount'].values()), 2)
        self.assertEqual(sum(result['cost_explicit_category'].values()), 1)

    def test_mapping_all_image_extensions_and_unique_identity(self):
        self.assertEqual(repair_name('妫€鏌ユ姤鍛婂崟'), '检查报告单')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('gold', 'images', 'ocr'):
                (root/name/'case').mkdir(parents=True)
            (root/'images/case/检查报告单_1_123.JPEG').write_bytes(b'synthetic-image')
            write(root/'gold/case/妫€鏌ユ姤鍛婂崟_1_123.json', {'fields': {'diagnosis': ['肺炎']}})
            write(root/'ocr/case/检查报告单_1_123.json', {'text': '诊断：肺炎'})
            result = mapping(root/'gold', root/'images', root/'ocr')
            self.assertEqual(result['summary']['mapped'], 1)
            self.assertEqual(result['summary']['ocr_available'], 1)
            self.assertEqual(result['documents'][0]['mapping_method'], 'reversible_filename_encoding')

    def test_missing_predictions_not_removed_and_exact_matches_are_one_to_one(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write(root/'gold.json', {'fields': {'diagnosis': ['甲', '乙']}})
            from scripts.preliminary_kr1 import sha
            row = {'document_id': 'doc', 'reference': str(root/'gold.json'),
                   'reference_sha256': sha(root/'gold.json'), 'image_sha256': 'image', 'ocr_sha256': 'ocr'}
            manifest = {'documents': [row]}
            result = score(manifest, root/'predictions')
            self.assertEqual(result['overall']['fn'], 2)
            write(root/'predictions/doc.json', {'status': 'completed', 'image_sha256': 'image',
                  'ocr_sha256': 'ocr', 'result': {'fields': {'diagnosis': ['甲', '甲']}}})
            result = score(manifest, root/'predictions')
            self.assertEqual((result['overall']['tp'], result['overall']['fp'], result['overall']['fn']), (1, 1, 1))
            self.assertFalse(result['five_core_categories_fully_annotated'])

    def test_field_confidence_and_evidence_required(self):
        self.assertEqual(original_quote('诊断：\n肺炎（疑似）', '诊断:肺炎(疑似)'), '诊断：\n肺炎（疑似）')
        self.assertIsNone(original_quote('诊断：肺炎（疑似）', '诊断：肺癌'))
        with self.assertRaises(ValidationError):
            DocumentPrediction(fields={'diagnosis': ['肺炎']})
        self.assertEqual(DocumentPrediction(fields={'diagnosis': ['肺炎']}, confidence={'diagnosis': .8},
                         evidence={'diagnosis': '诊断：肺炎'}).fields['diagnosis'], ['肺炎'])
        repaired = parse_prediction(json.dumps({'diagnosis': ['肺炎'], 'confidence': {'diagnosis': .8},
                                               'evidence': {'diagnosis': '诊断：肺炎'}}))
        self.assertEqual(repaired.fields['diagnosis'], ['肺炎'])
