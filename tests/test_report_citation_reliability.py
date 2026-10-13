import json
import unittest
from uuid import uuid4
from unittest.mock import MagicMock

from services.api.app.conversation_agent import run_agent
from services.api.app.inline_citations import canonical_analysis_citations
from services.api.app.generation_errors import generation_error_code
from services.api.app.analysis_review import AnalysisReview


class ReviewedModel:
    supports_inline_citations=True
    def __init__(self,draft):
        self.complete=MagicMock(return_value={'content':json.dumps(draft)})
        self.reviewed=[]
    def review_analysis(self,packed,text,citations=None):
        self.reviewed.append((packed,citations))
        return AnalysisReview(accepted=True,issues=[])


class ReportCitationReliabilityTests(unittest.TestCase):
    def fixture(self):
        refs=[str(uuid4()) for _ in range(1559)]
        evidence=[{'evidence_id':ref,'document_id':str(i%15),'page_index':0,'text':'原文片段'}
                  for i,ref in enumerate(refs)]
        cited=refs[-24:]
        draft={'text':'\n'.join(f'第{i}条原文事实。' for i in range(24)),
               'evidence_refs':cited[:20],'knowledge_refs':[],'history_refs':[],
               'citations':[{'quote':f'第{i}条原文事实。','source_refs':[ref]} for i,ref in enumerate(cited)]}
        tools=MagicMock()
        def page(name,arguments):
            self.assertEqual(name,'read_materials')
            args=json.loads(arguments);start=args['offset'];end=start+args['page_size']
            return {'status':'available','evidence':evidence[start:end],
                    'next_offset':end if end<len(evidence) else None}
        tools.execute.side_effect=page
        return cited,draft,tools,ReviewedModel(draft)

    def test_large_case_reads_all_sources_and_derives_24_references_without_repair(self):
        cited,draft,tools,model=self.fixture()
        reply,events=run_agent([], '解释', [],tools,model=model,analysis_mode=True)
        self.assertEqual(tools.execute.call_count,8)
        self.assertEqual(len(events),8)
        self.assertEqual(reply['performance']['source_fragments'],1559)
        self.assertTrue(reply['performance']['source_read_complete'])
        self.assertEqual(reply['evidence_refs'],cited)
        model.complete.assert_called_once()
        self.assertEqual(len(model.reviewed),1)

    def test_older_draft_with_incomplete_summary_is_reused_after_source_checks(self):
        cited,draft,tools,model=self.fixture()
        reply,_=run_agent([], '解释', [],tools,model=model,analysis_mode=True,initial_analysis=draft)
        model.complete.assert_not_called()
        self.assertTrue(reply['performance']['draft_reused'])
        self.assertEqual(reply['evidence_refs'],cited)
        self.assertEqual(len(model.reviewed),1)

    def test_unknown_citation_is_rejected_instead_of_added_to_summary(self):
        _,draft,tools,model=self.fixture()
        draft['citations'][0]['source_refs']=['S9999']
        model.complete.return_value={'content':json.dumps(draft)}
        with self.assertRaisesRegex(ValueError,'CITATION_SOURCE_NOT_AUTHORIZED'):
            run_agent([], '解释', [],tools,model=model,analysis_mode=True)
        self.assertEqual(len(model.reviewed),0)

    def test_stalled_pagination_fails_before_paid_generation(self):
        _,_,tools,model=self.fixture()
        tools.execute.side_effect=None
        tools.execute.return_value={'status':'available','evidence':[],'next_offset':0}
        with self.assertRaisesRegex(RuntimeError,'ANALYSIS_SOURCE_PAGING_INVALID'):
            run_agent([], '解释', [],tools,model=model,analysis_mode=True)
        model.complete.assert_not_called()

    def test_unretrieved_knowledge_is_not_authorized_by_model_metadata(self):
        data={'text':'一般解释。','citations':[{'quote':'一般解释。','source_refs':['TY-COST-01']}],
              'evidence_refs':[],'knowledge_refs':['TY-COST-01']}
        with self.assertRaisesRegex(ValueError,'CITATION_SOURCE_NOT_AUTHORIZED'):
            canonical_analysis_citations(data,{},[])

    def test_reference_limit_is_explicit_and_never_silently_trims(self):
        refs=[str(uuid4()) for _ in range(81)]
        data={'text':'\n'.join(f'原文第{i}项。' for i in range(14)),
              'citations':[{'quote':f'原文第{i}项。','source_refs':refs[i*6:(i+1)*6]} for i in range(14)]}
        with self.assertRaisesRegex(ValueError,'ANALYSIS_CITATION_LIMIT'):
            canonical_analysis_citations(data,{f'S{i}':ref for i,ref in enumerate(refs)},[])

    def test_failure_classification_never_records_arbitrary_exception_text(self):
        self.assertEqual(generation_error_code(ValueError('CITATION_SOURCE_NOT_AUTHORIZED')),
                         'CITATION_SOURCE_NOT_AUTHORIZED')
        self.assertEqual(generation_error_code(ValueError('private patient text or credential')),
                         'AGENT_UNAVAILABLE')

