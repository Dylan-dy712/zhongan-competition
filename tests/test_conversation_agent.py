import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.api.app.conversation_agent import AgentReply, AgentModel, CareTools, run_agent
from services.api.app.repository import AccessDenied


def call(name, args=None):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'tool-1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args or {})}}]}


def answer(text='你好', refs=None):
    return {'role': 'assistant', 'content': json.dumps({'text': text, 'evidence_refs': refs or [], 'history_refs': []})}


class AgentTests(unittest.TestCase):
    def test_analysis_reads_all_source_pages_before_writing_free_text(self):
        model, tools = MagicMock(), MagicMock()
        ref1, ref2 = str(uuid4()), str(uuid4())
        tools.execute.side_effect = [
            {'status':'available','evidence':[{'evidence_id':ref1,'text':'医疗总费用120元'}],'next_offset':8},
            {'status':'available','evidence':[{'evidence_id':ref2,'text':'不能排除肺炎'}],'next_offset':None}]
        model.complete.return_value = answer('票据记载120元。\n\n检查记录写到不能排除肺炎。',[ref1,ref2])
        reply, events = run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        sent = model.complete.call_args.args[0]
        payloads = json.loads(sent[-1]['content'])['authorized_material_pages']
        self.assertEqual(len(payloads), 1)
        self.assertIn('不能排除肺炎', str(payloads))
        self.assertEqual(reply['prompt_version'], 'patient-analysis-narrative-v8-shared-draft')
        self.assertEqual(reply['text'], '票据记载120元。\n\n检查记录写到不能排除肺炎。')
        self.assertEqual(len(events), 2)
        self.assertEqual(json.loads(tools.execute.call_args_list[1].args[1]),
                         {'offset':8,'page_size':200,'balanced':True})

    def test_analysis_keeps_text_budget_even_when_one_batch_is_large(self):
        model,tools=MagicMock(),MagicMock()
        ref=str(uuid4())
        tools.execute.return_value={'status':'available','next_offset':None,'evidence':[
            {'evidence_id':ref,'text':'合成来源'}, {'evidence_id':str(uuid4()),'text':'长'*28000}]}
        model.complete.return_value=answer('本轮只解读已读取的部分。',[ref])
        run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        messages=model.complete.call_args.args[0]
        data=json.loads(messages[-2]['content'])['authorized_material_pages'][0]['spans']
        self.assertEqual(len(data),1)
        self.assertIn('未覆盖全部页',messages[-1]['content'])

    def test_analysis_partial_read_is_explicit_and_bounded(self):
        model, tools = MagicMock(), MagicMock()
        ref=str(uuid4())
        tools.execute.return_value={'status':'available','evidence':[{'text':'synthetic','evidence_id':ref}], 'next_offset':8}
        model.complete.return_value=answer('本轮只解读已读取的部分。',[ref])
        run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        self.assertEqual(tools.execute.call_count, 6)
        self.assertFalse(model.complete.call_args.kwargs['allow_tools'])
        self.assertIn('不得把未读取的内容说成缺资料', str(model.complete.call_args.args[0]))

    def test_analysis_repairs_excess_citations_with_the_actual_schema_budget(self):
        refs=[str(uuid4()) for _ in range(21)]
        model,tools=MagicMock(),MagicMock()
        tools.execute.return_value={'status':'available','next_offset':None,
                                    'evidence':[{'evidence_id':ref,'text':'合成材料'} for ref in refs]}
        model.complete.side_effect=[answer('材料解读',refs),answer('材料解读',refs[:5])]
        reply,_=run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        self.assertEqual(reply['evidence_refs'],refs[:5])
        messages=model.complete.call_args.args[0]
        self.assertIn('evidence_refs只填这些短编号，最多20个',messages[0]['content'])
        self.assertIn('最多20个材料中S1等短编号',messages[-1]['content'])
        self.assertIn('evidence_refs:too_long',messages[-1]['content'])
        self.assertEqual(model.complete.call_count,2)

    def test_analysis_with_sources_requires_citations_and_rejects_unsafe_advice(self):
        for text, refs, error in [('未引用的分析', [], 'UNSOURCED_ANALYSIS'),
                                   ('请自行停药', [str(uuid4())], 'UNSAFE_ANALYSIS')]:
            with self.subTest(text=text):
                model,tools=MagicMock(),MagicMock()
                tools.execute.return_value={'status':'available','evidence':[{'text':'合成票据','evidence_id':refs[0] if refs else str(uuid4())}],'next_offset':None}
                model.complete.return_value=answer(text,refs)
                with self.assertRaisesRegex(ValueError,error):
                    run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)

    def test_analysis_does_not_read_unavailable_sources(self):
        model,tools=MagicMock(),MagicMock()
        tools.execute.return_value={'status':'failed'}
        with self.assertRaisesRegex(RuntimeError,'ANALYSIS_SOURCES_UNAVAILABLE'):
            run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        model.complete.assert_not_called()

    def test_short_sources_resolve_to_only_the_actual_read_evidence(self):
        model,tools=MagicMock(),MagicMock()
        ref=str(uuid4())
        tools.execute.return_value={'status':'available','next_offset':None,
                                    'evidence':[{'evidence_id':ref,'text':'不能排除肺炎'}]}
        model.complete.return_value=answer('不能排除不等于确诊。',['S1'])
        reply,_=run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        self.assertEqual(reply['evidence_refs'],[ref])
        self.assertEqual(reply['performance']['source_fragments'],1)
        tools.validate_reply.assert_called_once()
        model.complete.return_value=answer('错误来源',['S2'])
        with self.assertRaisesRegex(ValueError,'UNKNOWN_EVIDENCE_REFERENCE'):
            run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)

    def test_repeated_same_source_does_not_trigger_another_model_call(self):
        model,tools=MagicMock(),MagicMock()
        ref=str(uuid4())
        tools.execute.return_value={'status':'available','next_offset':None,
                                    'evidence':[{'evidence_id':ref,'text':'费用120元'}]}
        model.complete.return_value=answer('票据记载120元。',['S1']*30)
        reply,_=run_agent([], '解释资料', [], tools, model=model, analysis_mode=True)
        self.assertEqual(reply['evidence_refs'],[ref])
        self.assertEqual(model.complete.call_count,1)

    def test_analysis_model_allows_longer_reasoning_without_changing_normal_chat(self):
        with patch('services.api.app.conversation_agent.OpenAiCompatibleExtractor') as config, \
             patch('services.api.app.conversation_agent.requests.post') as post:
            config.return_value.base_url='https://example.invalid'
            post.return_value.json.return_value={'choices':[{'message':answer()}]}
            AgentModel(analysis_mode=True).complete([])
            self.assertEqual(post.call_args.kwargs['timeout'],(10,180))
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'],16000)
            self.assertNotIn('tools',post.call_args.kwargs['json'])
            AgentModel().complete([])
            self.assertEqual(post.call_args.kwargs['timeout'],(5,20))
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'],2200)

    def test_can_chat_without_report_and_receives_previous_turn(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.return_value = answer('你刚才说担心费用，我们可以先核对票据。')
        history = [{'status': 'completed', 'question': '我担心费用', 'answer': {'text': '可以上传票据。'}}]
        reply, events = run_agent(history, '那我该传什么？', [], tools, model=model)
        sent = model.complete.call_args.args[0]
        self.assertEqual(sent[1]['content'], '我担心费用')
        self.assertIn('那我该传什么', sent[-1]['content'])
        tools.execute.assert_not_called()
        self.assertEqual(events, [])
        self.assertIn('费用', reply['text'])

    def test_model_selects_tools_and_sees_actual_results(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.side_effect = [call('start_analysis'), answer('材料已排队，完成后接着解释。')]
        tools.execute.return_value = {'status': 'queued', 'run_id': str(uuid4())}
        reply, events = run_agent([], '分析附件', [], tools, model=model)
        tools.execute.assert_called_once_with('start_analysis', '{}')
        sent = model.complete.call_args.args[0]
        result = next(m for m in sent if m['role'] == 'tool')
        self.assertEqual(json.loads(result['content'])['status'], 'queued')
        self.assertEqual(events[0]['status'], 'queued')

    def test_history_lookup_is_a_model_selected_tool(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.side_effect = [call('search_history', {'query':'费用'}), answer('上次你关注的是费用。')]
        tools.execute.return_value = {'status':'found','messages':[{'question':'费用看不懂'}]}
        run_agent([], '我上次问了什么', [], tools, model=model)
        self.assertEqual(tools.execute.call_args.args[0], 'search_history')

    def test_tool_loop_is_bounded(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.side_effect = [call('list_materials')] * 5
        tools.execute.return_value = {'documents': []}
        with self.assertRaisesRegex(RuntimeError, 'AGENT_TOOL_LIMIT'):
            run_agent([], '反复查', [], tools, model=model)
        self.assertEqual(tools.execute.call_count, 4)
        self.assertFalse(model.complete.call_args.kwargs['allow_tools'])

    def test_invalid_tool_arguments_do_not_execute_a_fallback(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.side_effect = [call('read_materials', {'case_id': str(uuid4())}), answer('需要确认材料。')]
        tools.execute.side_effect = ValueError('invalid argument')
        reply, events = run_agent([], '读取材料', [], tools, model=model)
        self.assertEqual(events[0]['status'], 'invalid_arguments')

    def test_access_denied_is_not_fed_back_as_success(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.return_value = call('search_history')
        tools.execute.side_effect = AccessDenied()
        with self.assertRaises(AccessDenied):
            run_agent([], '读取别人历史', [], tools, model=model)

    def test_unseen_evidence_cannot_be_cited(self):
        tools = CareTools(MagicMock(), uuid4(), uuid4())
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_EVIDENCE_REFERENCE'):
            tools.validate_reply(AgentReply(text='结论', evidence_refs=[uuid4()]))

    def test_unseen_history_cannot_be_cited(self):
        tools = CareTools(MagicMock(), uuid4(), uuid4())
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_HISTORY_REFERENCE'):
            tools.validate_reply(AgentReply(text='回忆', history_refs=[uuid4()]))

    def test_context_budget_keeps_latest_exchange(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.return_value = answer()
        history=[{'status':'completed','question':'旧消息'*7000,'answer':{'text':'旧'}},
                 {'status':'completed','question':'最近一次','answer':{'text':'最近回答'}}]
        run_agent(history, '继续', [], tools, model=model)
        sent=model.complete.call_args.args[0]
        self.assertEqual(len(sent),4)
        self.assertEqual(sent[1]['content'],'最近一次')

    def test_invalid_reply_format_gets_one_bounded_repair(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.side_effect = [{'role':'assistant','content':'hello'}, answer('你好')]
        reply, _ = run_agent([], '你好', [], tools, model=model)
        self.assertEqual(reply['text'], '你好')
        self.assertEqual(model.complete.call_count, 2)

    def test_invalid_reply_format_does_not_loop_forever(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.return_value = {'role':'assistant','content':'not json'}
        with self.assertRaises(ValueError):
            run_agent([], '你好', [], tools, model=model)
        self.assertEqual(model.complete.call_count, 2)


if __name__ == '__main__':
    unittest.main()
