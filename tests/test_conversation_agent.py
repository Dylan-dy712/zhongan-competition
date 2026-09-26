import json
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.api.app.conversation_agent import AgentReply, CareTools, run_agent
from services.api.app.repository import AccessDenied


def call(name, args=None):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'tool-1', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args or {})}}]}


def answer(text='你好', refs=None):
    return {'role': 'assistant', 'content': json.dumps({'text': text, 'evidence_refs': refs or [], 'history_refs': []})}


class AgentTests(unittest.TestCase):
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
