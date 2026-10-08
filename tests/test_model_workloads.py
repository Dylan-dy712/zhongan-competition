import unittest
from unittest.mock import patch
from services.api.app.model_workloads import workload_options
from services.api.app.conversation_agent import AgentModel
from services.api.app.llm_extractor import OpenAiCompatibleExtractor


class ModelWorkloadTests(unittest.TestCase):
    def test_only_documented_official_model_receives_workload_settings(self):
        self.assertEqual(workload_options('https://api.deepseek.com/v1','deepseek-flash','narrative'),
                         {'thinking':{'type':'disabled'}})
        self.assertEqual(workload_options('https://api.deepseek.com','deepseek-flash','review'),
                         {'thinking':{'type':'enabled'},'reasoning_effort':'low'})
        self.assertEqual(workload_options('https://proxy.invalid','deepseek-flash','narrative'),{})
        self.assertEqual(workload_options('https://api.deepseek.com','other-model','narrative'),{})

    def test_narrative_uses_fast_generation_and_normal_chat_stays_unchanged(self):
        with patch('services.api.app.conversation_agent.OpenAiCompatibleExtractor') as config, \
             patch('services.api.app.conversation_agent.requests.post') as post:
            config.return_value.base_url='https://api.deepseek.com'
            config.return_value.model_id='deepseek-flash'
            post.return_value.json.return_value={'choices':[{'message':{'content':'{}'}}]}
            AgentModel(analysis_mode=True).complete([])
            self.assertEqual(post.call_args.kwargs['json']['thinking'],{'type':'disabled'})
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'],8000)
            AgentModel().complete([])
            self.assertNotIn('thinking',post.call_args.kwargs['json'])

    def test_extraction_and_review_send_their_respective_settings(self):
        with patch('services.api.app.llm_extractor.requests.post') as post:
            client=object.__new__(OpenAiCompatibleExtractor)
            client.base_url='https://api.deepseek.com';client.model_id='deepseek-flash';client.api_key='synthetic'
            post.return_value.json.return_value={'choices':[{'message':{'content':'{}'}}]}
            client._call([],workload='extraction')
            self.assertEqual(post.call_args.kwargs['json']['thinking'],{'type':'disabled'})
            client._call([])
            self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'low')
