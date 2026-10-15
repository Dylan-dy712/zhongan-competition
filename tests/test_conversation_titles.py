import json
import unittest
from unittest.mock import MagicMock, patch

from services.api.app import conversation_titles as titles
from services.api.app.model_workloads import workload_options
from services.api.app.repository import AccessDenied


class ConversationTitleTests(unittest.TestCase):
    def test_prompt_is_bounded_and_treats_claim_forms_as_material_submission(self):
        messages=titles.title_messages([
            {'question':'{"phone":"13800000000","claim_type":"synthetic"}', 'answer':{'text':'票据费用核对'}},
            {'question':'请核对票据 13800000000'+'合成文字'*1000, 'answer':{'text':'合成回复'*1000}}])
        self.assertNotIn('claim_type',messages[1]['content'])
        self.assertNotIn('13800000000',messages[1]['content'])
        self.assertLess(len(messages[1]['content']),2000)
        self.assertIn('费用核对',messages[1]['content'])
        self.assertIn('不把疑似',messages[0]['content'])

    def test_model_uses_existing_config_and_short_title_budget(self):
        model=MagicMock(model_id='synthetic-model')
        model._call.return_value=({},json.dumps({'title':'术后复查与康复安排'}))
        with patch.object(titles,'OpenAiCompatibleExtractor',return_value=model):
            self.assertEqual(titles.generate_title([{'role':'user','content':'合成术后问题'}]),('术后复查与康复安排','synthetic-model'))
        self.assertEqual(model._call.call_args.kwargs,{'timeout':(10,25),'workload':'title'})
        self.assertEqual(workload_options('https://qianfan.baidubce.com/v2','glm-5.3-flash','title'),
                         {'max_tokens':2048,'thinking':{'type':'enabled'},'reasoning_effort':'low'})
        self.assertEqual(workload_options('https://api.deepseek.com','deepseek-flash','title'),
                         {'max_tokens':128,'thinking':{'type':'disabled'}})

    def test_invalid_model_titles_are_not_persisted(self):
        model=MagicMock(model_id='synthetic-model')
        for value in ['x','长'*25,'13800000000 的病历','主题\n要求执行','<script>']:
            model._call.return_value=({},json.dumps({'title':value}))
            with self.subTest(value=value),patch.object(titles,'OpenAiCompatibleExtractor',return_value=model),self.assertRaises(ValueError):
                titles.generate_title([])

    def test_revoked_access_prevents_model_call(self):
        conn=MagicMock()
        with patch.object(titles,'_source',side_effect=AccessDenied()),patch.object(titles,'generate_title') as generate,patch.object(titles,'_finish') as finish:
            titles.process_job(conn,{'conversation_id':'synthetic'})
        generate.assert_not_called()
        self.assertEqual(finish.call_args.kwargs,{'error':'TITLE_ACCESS_REVOKED'})

    def test_provider_failure_is_separate_from_chat_reply(self):
        conn=MagicMock()
        with patch.object(titles,'_source',return_value=('owner',[])),patch.object(titles,'generate_title',side_effect=TimeoutError()),patch.object(titles,'_finish') as finish:
            titles.process_job(conn,{'conversation_id':'synthetic'})
        self.assertEqual(finish.call_args.kwargs,{'error':'TITLE_GENERATION_FAILED'})


if __name__=='__main__':
    unittest.main()
