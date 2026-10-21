import copy,unittest
from uuid import uuid4
from services.api.app.citation_spans import VERSION,locator,resolve,local_box


class CitationSpanTests(unittest.TestCase):
    def setUp(self):
        self.page={'evidence_id':uuid4(),'run_id':uuid4(),'case_id':uuid4(),'document_id':uuid4(),
            'document_version':1,'page_index':0,'source_hash':'a'*64,'parser_version':'synthetic-ocr',
            'text_value':'费用总额：100.00元\n床位费：20.00元\n术后按医嘱复诊。'}
        self.rows=[];offset=0
        for index,text in enumerate(self.page['text_value'].splitlines()):
            self.rows.append({**self.page,'evidence_id':uuid4(),'text_start':offset,'text_end':offset+len(text),
                'text_value':text,'bbox':[.1,.1+index*.2,.7,.14+index*.2]})
            offset+=len(text)+1
        self.draft={'text':'本次总费用为100元。床位费为20元。','evidence_refs':[str(self.page['evidence_id'])],'knowledge_refs':[],
            'citations':[{'quote':text,'source_refs':[str(self.page['evidence_id'])]} for text in ['本次总费用为100元。','床位费为20元。']]}
        self.plan={'version':VERSION,'review_passed':True,'citations':[
            {'quote':c['quote'],'sources':[locator(self.page,self.rows[i])]} for i,c in enumerate(self.draft['citations'])]}

    def test_different_claims_on_same_page_get_distinct_exact_text_and_local_boxes(self):
        reply,rows=resolve(self.draft,self.plan,[self.page],self.rows)
        self.assertEqual(reply['text'],self.draft['text'])
        self.assertEqual([r['text_value'] for r in rows],['费用总额：100.00元','床位费：20.00元'])
        self.assertNotEqual(reply['citations'][0]['source_refs'],reply['citations'][1]['source_refs'])
        self.assertNotIn(str(self.page['evidence_id']),reply['evidence_refs'])
        for row in rows:
            self.assertEqual(row['text_value'],self.page['text_value'][row['text_start']:row['text_end']])
            self.assertTrue(local_box(row['bbox']))
            self.assertLess(len(row['text_value']),len(self.page['text_value']))
        again,other=resolve(self.draft,self.plan,[self.page],self.rows)
        self.assertEqual(reply,again)
        self.assertEqual([r['evidence_id'] for r in rows],[r['evidence_id'] for r in other])

    def test_context_lines_can_merge_only_when_exact_contiguous_and_spatially_local(self):
        self.rows[1]['bbox']=[.1,.15,.7,.18]
        self.plan['citations'][0]['sources'].append(locator(self.page,self.rows[1]))
        reply,rows=resolve(self.draft,self.plan,[self.page],self.rows)
        self.assertEqual(rows[0]['text_value'],'费用总额：100.00元\n床位费：20.00元')
        self.assertLess(rows[0]['bbox'][3]-rows[0]['bbox'][1],.1)

    def test_unreviewed_changed_text_or_wrong_page_never_becomes_a_citation(self):
        for mutate in [lambda p:p.update(review_passed=False),
            lambda p:p['citations'][0].update(quote='另一条结论'),
            lambda p:p['citations'][0]['sources'][0].update(text_sha256='b'*64),
            lambda p:p['citations'][0]['sources'][0].update(page_key='c'*64)]:
            plan=copy.deepcopy(self.plan);mutate(plan)
            with self.assertRaises(ValueError):resolve(self.draft,plan,[self.page],self.rows)
        with self.assertRaises(ValueError):locator(self.page,{**self.rows[0],'bbox':[0,0,1,1]})

    def test_only_explicitly_reviewed_nonfactual_links_may_be_omitted(self):
        plan=copy.deepcopy(self.plan);plan['citations'][0]['sources']=[]
        with self.assertRaises(ValueError):resolve(self.draft,plan,[self.page],self.rows)
        plan['citations'][0]['omit']=True
        reply,rows=resolve(self.draft,plan,[self.page],self.rows)
        self.assertEqual(reply['text'],self.draft['text'])
        self.assertEqual(len(reply['citations']),1)


if __name__=='__main__':unittest.main()
