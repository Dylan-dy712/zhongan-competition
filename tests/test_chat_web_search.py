import json
import unittest
from unittest.mock import MagicMock,patch
from uuid import uuid4
from services.api.app.conversation_agent import CareTools,WebSearchArgs,run_agent
from pydantic import ValidationError

class ChatWebSearchTests(unittest.TestCase):
    def setUp(self):
        self.doc={'entry_id':'WEB-VOLC-'+'a'*24,'title':'合成医保公开说明','source':'https://www.nhsa.gov.cn/test',
            'content':'甲类与乙类的合成公开定义。','version':'test-v1','scope':'一般解释，不推算个人报销。',
            'retrieval_provider':'volcengine','published_at':'2026-01-01','retrieved_at':'2026-10-16'}

    def test_category_question_actually_searches_before_answer_and_builds_citations(self):
        tools=CareTools(MagicMock(),uuid4(),uuid4())
        model=MagicMock()
        model.complete.return_value={'content':json.dumps({'paragraphs':[
            {'text':'甲类与乙类的合成公开定义。','source_refs':[self.doc['entry_id']]}]})}
        service=MagicMock()
        service.search.return_value={'status':'cached','results':[self.doc],'calls':0}
        service.resolve.return_value=self.doc
        events=[]
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':uuid4()}), \
             patch('services.api.app.conversation_agent.WebKnowledge',return_value=service), \
             patch('services.api.app.web_knowledge.WebKnowledge',return_value=service):
            reply,final_events=run_agent([], '费用清单上甲类、乙类、丙类是什么意思？',[],tools,model=model,
                on_event=lambda items:events.append([dict(item) for item in items]))
        service.search.assert_called_once_with({'term':'医保目录分类','slot':'COST'})
        self.assertEqual(events[0],[{'tool':'search_web','status':'running'}])
        self.assertEqual(final_events,[{'tool':'search_web','status':'cached'}])
        self.assertEqual(reply['knowledge_sources'][0]['source'],'https://www.nhsa.gov.cn/test')
        self.assertEqual(reply['citations'][0]['quote'],reply['text'])
        self.assertEqual(model.complete.call_count,1)

    def test_missing_network_result_can_be_explained_without_a_failed_turn(self):
        tools=CareTools(MagicMock(),uuid4(),uuid4());model=MagicMock();service=MagicMock()
        service.search.return_value={'status':'unavailable','results':[],'calls':1}
        model.complete.return_value={'content':json.dumps({'paragraphs':[{'text':'联网资料暂时不可用，可以先向结算窗口核对适用的政策。','source_refs':[]}]})}
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':uuid4()}), \
             patch('services.api.app.conversation_agent.WebKnowledge',return_value=service):
            reply,events=run_agent([], '甲类和乙类是什么意思？',[],tools,model=model)
        self.assertIn('暂时不可用',reply['text'])
        self.assertEqual(reply['knowledge_sources'],[])
        self.assertEqual(events[0]['status'],'unavailable')

    def test_public_tool_rejects_raw_queries_and_bounds_topics_per_turn(self):
        with self.assertRaises(ValidationError):WebSearchArgs(topic='张三13800000000的病历')
        tools=CareTools(MagicMock(),uuid4(),uuid4());service=MagicMock()
        service.search.return_value={'status':'no_authoritative_results','results':[],'calls':1}
        with patch('services.api.app.conversation_agent.require_conversation',return_value={'case_id':uuid4()}), \
             patch('services.api.app.conversation_agent.WebKnowledge',return_value=service):
            for topic in ('医保目录分类','医保目录分类','医保起付线','医保封顶线'):
                result=tools.execute('search_web',json.dumps({'topic':topic}))
        self.assertEqual(service.search.call_count,2)
        self.assertEqual(result['status'],'turn_limit')
