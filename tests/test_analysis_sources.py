import json
import unittest
from uuid import uuid4
from services.api.app.analysis_sources import pack_sources


class SourcePackingTests(unittest.TestCase):
    def test_preserves_every_span_and_page_without_repeated_identifiers(self):
        doc1,doc2=str(uuid4()),str(uuid4())
        refs=[str(uuid4()) for _ in range(3)]
        rows=[{'evidence_id':refs[0],'document_id':doc1,'page_index':0,'text':'不能排除肺炎'},
              {'evidence_id':refs[1],'document_id':doc2,'page_index':1,'text':'个人自费120元'},
              {'evidence_id':refs[2],'document_id':doc1,'page_index':0,'text':'否认既往病史'}]
        packed,mapping=pack_sources([{'evidence':rows[:2]},{'evidence':rows[2:]}])
        self.assertEqual(mapping,dict(zip(['S1','S2','S3'],refs)))
        self.assertEqual(packed[0],{'document':'D1','page':0,'spans':[['S1','不能排除肺炎'],['S3','否认既往病史']]})
        self.assertEqual(packed[1]['page'],1)
        self.assertNotIn(doc1,json.dumps(packed))
        self.assertEqual(sum(len(p['spans']) for p in packed),3)

    def test_deduplicates_pagination_repeats_and_reduces_large_ocr_payload(self):
        rows=[{'evidence_id':str(uuid4()),'document_id':str(uuid4()) if i==0 else 'same-document',
               'page_index':0,'text':'合成OCR片段'} for i in range(857)]
        packed,mapping=pack_sources([{'evidence':rows},{'evidence':[rows[0]]}])
        self.assertEqual(len(mapping),857)
        self.assertLess(len(json.dumps(packed,ensure_ascii=False)),len(json.dumps(rows,ensure_ascii=False))*0.3)
