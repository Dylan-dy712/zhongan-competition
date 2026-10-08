import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.api.app.knowledge_retrieval import KnowledgeRetriever
from services.api.app.conversation_agent import AgentReply, CareTools, run_agent
from services.api.app.knowledge_assembler import PackExcludedError
from scripts.build_rag_corpus import split_content


def documents():
    return [dict(entry_id='TY-COST-01',title='个人自费和自付',content='个人自费是目录外费用。',
                 disease_code='TY',source='合成费用资料',scope='费用术语',source_path='test.md',
                 status='draft-待医学审核',numeric_pending_review=False),
            dict(entry_id='FX-S1-01',title='骨折',content='骨折是骨的完整性中断。',
                 disease_code='FX',source='合成医学资料',scope='成人骨折',source_path='test.md',
                 status='draft-待医学审核',numeric_pending_review=False),
            dict(entry_id='FY-S1-01',title='肺炎',content='肺炎的康复。',disease_code='FY',
                 source='合成医学资料',scope='成人肺炎',source_path='test.md',
                 status='draft-待医学审核',numeric_pending_review=False)]


class RetrievalTests(unittest.TestCase):
    def test_retrieval_ranks_related_chunks_and_retains_provenance(self):
        retriever=KnowledgeRetriever(documents(),version='test-v1')
        result=retriever.search('个人自费是什么')
        self.assertEqual(result['results'][0]['entry_id'],'TY-COST-01')
        self.assertEqual(result['results'][0]['status'],'draft-待医学审核')
        self.assertEqual(result['results'][0]['version'],'test-v1')
        self.assertEqual(result['results'][0]['source'],'合成费用资料')
        self.assertEqual(retriever.search('量子力学')['results'],[])
        self.assertEqual(retriever.search('')['results'],[])

    def test_disease_filters_and_scope_exclusions(self):
        retriever=KnowledgeRetriever(documents())
        self.assertFalse(retriever.search('骨折',disease_code='FY')['results'])
        retriever.assembler=MagicMock()
        retriever.assembler.check_exclusions.side_effect=PackExcludedError('KP-FX','合成排除条件')
        self.assertEqual(retriever.search('骨折',disease_code='FX',case_text='排除情境')['results'],[])

    def test_loaded_user_library_and_cost_chunks_have_integrity(self):
        retriever=KnowledgeRetriever()
        self.assertGreaterEqual(len(retriever.documents),735)
        self.assertTrue(retriever.search('骨折')['results'])
        self.assertTrue(retriever.search('个人自费')['results'])
        self.assertTrue(any(d['entry_id'].startswith('COST-DOC-') for d in retriever.documents))
        self.assertTrue(all(d['source'] for d in retriever.documents))

    def test_chunking_preserves_long_paragraphs_without_unbounded_chunks(self):
        original='骨折说明'*500
        chunks=list(split_content('# 标题\n'+original,max_chars=300))
        self.assertEqual(''.join(body for _,body in chunks),original)
        self.assertTrue(all(len(body)<=300 for _,body in chunks))

    def test_forged_knowledge_citation_is_rejected(self):
        tools=CareTools(MagicMock(),uuid4(),uuid4())
        with self.assertRaisesRegex(ValueError,'UNKNOWN_KNOWLEDGE_REFERENCE'):
            tools.validate_reply(AgentReply(text='回答',knowledge_refs=['TY-COST-01']))

    def test_answer_injects_retrieved_context_and_emits_only_valid_sources(self):
        retriever=KnowledgeRetriever(documents(),version='test-v1')
        conn=MagicMock()
        conn.execute.return_value.fetchall.return_value=[]
        tools=CareTools(conn,uuid4(),uuid4())
        model=MagicMock()
        model.complete.side_effect=[{'role':'assistant','tool_calls':[{'id':'k1','type':'function',
            'function':{'name':'search_knowledge','arguments':json.dumps({'query':'个人自费'})}}]},
            {'role':'assistant','content':json.dumps({'text':'一般来说，个人自费是目录外费用。',
             'knowledge_refs':['TY-COST-01'],'evidence_refs':[],'history_refs':[]})}]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':uuid4()}), \
             patch('services.api.app.conversation_agent.KnowledgeRetriever',return_value=retriever):
            result,events=run_agent([], '个人自费是什么', [],tools,model=model)
        self.assertEqual(result['knowledge_sources'][0]['source'],'合成费用资料')
        self.assertIn('目录外费用',str(model.complete.call_args.args[0]))
        self.assertEqual(events[0]['tool'],'search_knowledge')
        with patch('services.api.app.conversation_agent.KnowledgeRetriever',return_value=KnowledgeRetriever(documents(),version='new')):
            with self.assertRaisesRegex(ValueError,'STALE_KNOWLEDGE_REFERENCE'):
                tools.validate_reply(AgentReply(text='回答',knowledge_refs=['TY-COST-01']))


if __name__=='__main__':unittest.main()
