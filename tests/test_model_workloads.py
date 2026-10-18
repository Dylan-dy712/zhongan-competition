import unittest
import json
from unittest.mock import patch
from services.api.app.model_workloads import workload_options, uses_deepseek_strict
from services.api.app.conversation_agent import AgentModel
from services.api.app.llm_extractor import OpenAiCompatibleExtractor
from services.api.app.analysis_format import strict_analysis_tool,decode_analysis_tool


class ModelWorkloadTests(unittest.TestCase):
    def test_qianfan_all_workloads_use_low_thinking_budget(self):
        for workload in ['chat','extraction','narrative','review','fidelity']:
            options=workload_options('https://qianfan.baidubce.com/v2','glm-5.3-flash',workload)
            self.assertEqual(options,{'thinking':{'type':'enabled'},'reasoning_effort':'low','max_tokens':32768})
        self.assertFalse(uses_deepseek_strict('https://qianfan.baidubce.com/v2','glm-5.3-flash'))

    def test_qianfan_chat_and_analysis_never_use_deepseek_endpoint(self):
        with patch('services.api.app.conversation_agent.OpenAiCompatibleExtractor') as config, \
             patch('services.api.app.model_workloads.requests.Session') as session:
            config.return_value.base_url='https://qianfan.baidubce.com/v2'
            config.return_value.model_id='glm-5.3-flash'
            post=session.return_value.__enter__.return_value.post
            post.return_value.json.return_value={'choices':[{'message':{'content':'{}'}}]}
            for analysis in [False,True]:
                AgentModel(analysis_mode=analysis).complete([])
                self.assertEqual(post.call_args.args[0],'https://qianfan.baidubce.com/v2/chat/completions')
                self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'low')
                self.assertEqual(post.call_args.kwargs['json']['max_tokens'],32768)
                self.assertEqual(post.call_args.kwargs['timeout'],(10,180))

    def test_only_documented_official_model_receives_workload_settings(self):
        self.assertEqual(workload_options('https://api.deepseek.com/v1','deepseek-flash','narrative'),
                         {'thinking':{'type':'disabled'}})
        self.assertEqual(workload_options('https://api.deepseek.com','deepseek-flash','review'),
                         {'thinking':{'type':'enabled'},'reasoning_effort':'low'})
        self.assertEqual(workload_options('https://proxy.invalid','deepseek-flash','narrative'),{})
        self.assertEqual(workload_options('https://api.deepseek.com','other-model','narrative'),{})

    def test_fidelity_compares_sources_without_changing_professional_review(self):
        self.assertEqual(workload_options('https://api.deepseek.com','deepseek-flash','fidelity'),{'thinking':{'type':'disabled'}})
        self.assertEqual(workload_options('https://api.deepseek.com','deepseek-flash','review'),{'thinking':{'type':'enabled'},'reasoning_effort':'low'})

    def test_narrative_uses_fast_generation_and_normal_chat_stays_unchanged(self):
        with patch('services.api.app.conversation_agent.OpenAiCompatibleExtractor') as config, \
             patch('services.api.app.conversation_agent.requests.post') as post:
            config.return_value.base_url='https://api.deepseek.com'
            config.return_value.model_id='deepseek-flash'
            args={**{f'knowledge_{i}':'' for i in range(1,5)},'text':'材料解读',**{f'source_{i}':'S1' if i==1 else '' for i in range(1,21)}}
            post.return_value.json.return_value={'choices':[{'message':{'tool_calls':[{
                'function':{'name':'deliver_analysis','arguments':json.dumps(args)}}]}}]}
            narrative=AgentModel(analysis_mode=True)
            narrative.complete([{'role':'assistant','content':'先前的快速输出'}])
            self.assertEqual(post.call_args.kwargs['json']['thinking'],{'type':'disabled'})
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'],8000)
            self.assertEqual(post.call_args.args[0],'https://api.deepseek.com/beta/chat/completions')
            self.assertTrue(post.call_args.kwargs['json']['tools'][0]['function']['strict'])
            narrative.complete([])
            self.assertEqual(post.call_args.kwargs['json']['thinking'],{'type':'disabled'})
            self.assertTrue(post.call_args.kwargs['json']['tools'][0]['function']['strict'])
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'],8000)
            AgentModel().complete([])
            self.assertNotIn('thinking',post.call_args.kwargs['json'])

    def test_strict_format_limits_metadata_slots_and_keeps_free_text(self):
        schema=strict_analysis_tool()['function']['parameters']
        self.assertEqual(len(schema['properties']),29)
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['citations']['maxItems'],40)
        args={**{f'knowledge_{i}':'TY-COST-01' if i==1 else '' for i in range(1,5)},'text':'材料A的自由段落。\n\n材料B的自由段落。',
              **{f'source_{i}':'S37' if i==2 else '' for i in range(1,21)}}
        reply=decode_analysis_tool({'tool_calls':[{'function':{
            'name':'deliver_analysis','arguments':json.dumps(args)}}]})
        data=json.loads(reply['content'])
        self.assertEqual(data['text'],args['text'])
        self.assertEqual(data['evidence_refs'],['S37'])
        self.assertEqual(data['knowledge_refs'],['TY-COST-01'])
        args['source_21']='S99'
        with self.assertRaisesRegex(RuntimeError,'ANALYSIS_RESPONSE_FORMAT'):
            decode_analysis_tool({'tool_calls':[{'function':{
                'name':'deliver_analysis','arguments':json.dumps(args)}}]})

    def test_extraction_and_review_send_their_respective_settings(self):
        with patch('services.api.app.llm_extractor.requests.post') as post:
            client=object.__new__(OpenAiCompatibleExtractor)
            client.base_url='https://api.deepseek.com';client.model_id='deepseek-flash';client.api_key='synthetic'
            post.return_value.json.return_value={'choices':[{'message':{'content':'{}'}}]}
            client._call([],workload='extraction')
            self.assertEqual(post.call_args.kwargs['json']['thinking'],{'type':'disabled'})
            client._call([])
            self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'],'low')
