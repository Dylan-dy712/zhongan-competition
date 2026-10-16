import copy,os,unittest
from uuid import uuid4
from services.api.app.worker import evidence_for_page
from services.api.app.page_sources import narrative_page_source,readable_materials,VERSION

class PageSourceTests(unittest.TestCase):
    def test_page_source_keeps_every_readable_fragment_and_excludes_uncertain_ocr(self):
        document={'document_id':uuid4(),'document_version':1}
        page={'page_index':0,'text':'诊断\n待确认','metadata':{'ocr_method':'synthetic'},'blocks':[
            {'text':'诊断','bbox':[0,0,1,1],'metadata':{}},
            {'text':'不可靠的金额999','bbox':[0,0,1,1],'metadata':{'needs_clearer_photo':True}},
            {'text':'待确认','bbox':[0,0,1,1],'metadata':{}}]}
        words=evidence_for_page(document,page);before=copy.deepcopy(words)
        source=narrative_page_source(document,page,words)
        self.assertEqual(source['text'],'诊断\n待确认')
        self.assertEqual(source['extraction_method'],VERSION)
        self.assertEqual(words,before)
        self.assertNotIn(source['evidence_id'],{word['evidence_id'] for word in words})
        self.assertNotEqual(source['evidence_id'],narrative_page_source(document,page,words)['evidence_id'])

@unittest.skipUnless(os.environ.get('ZHONGAN_AUTH_TEST_DATABASE_URL'),'Native PostgreSQL not configured')
class PageSourceDatabaseTests(unittest.TestCase):
    def test_page_preference_is_scoped_to_exact_case_and_run_with_fragment_fallback(self):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL'],row_factory=dict_row) as conn:
            conn.execute('CREATE TEMP TABLE evidence(evidence_id uuid,document_id uuid,page_index integer,text_start integer,text_value text,case_id uuid,run_id uuid,extraction_method text)')
            case,other,run,oldrun,doc=uuid4(),uuid4(),uuid4(),uuid4(),uuid4()
            def add(owner,rid,text,method):
                conn.execute('INSERT INTO evidence VALUES(%s,%s,0,0,%s,%s,%s,%s)',(uuid4(),doc,text,owner,rid,method))
            add(case,run,'片段一','ocr');add(case,run,'片段二','ocr');add(case,run,'片段一\n片段二',VERSION)
            add(other,run,'其他病例整页',VERSION);add(case,oldrun,'旧版片段','ocr')
            self.assertEqual([r['text'] for r in readable_materials(conn,case,run,'%',10,0,True)],['片段一\n片段二'])
            self.assertEqual([r['text'] for r in readable_materials(conn,case,oldrun,'%',10,0,False)],['旧版片段'])
            self.assertEqual(readable_materials(conn,case,run,'%不存在%',10,0,True),[])
