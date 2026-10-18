import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError

from services.api.app.analysis_format import decode_analysis_tool, strict_analysis_tool
from services.api.app.conversation_agent import run_agent
from services.api.app import conversation_repository as chats
from services.api.app.patient_followup import ClarificationQuestion, FollowupPayload, PatientUpdate, source_patient_updates
from services.api.app.repository import AccessDenied, connect, token_digest


QUESTION = {'field': 'followup_time', 'question': '医生有交代什么时候复查吗？',
            'options': [{'label': '医生还没交代', 'message': '医生还没交代复查时间。'}]}
SUGGESTIONS = ['复查前需要准备哪些已有材料？', '这次票据上的总费用是什么意思？']


def response(**data):
    return {'content': json.dumps({'text': '咱们一起把后续安排记清楚。',
                                  'evidence_refs': [], 'history_refs': [], **data})}


class PatientFollowupTests(unittest.TestCase):
    def test_choice_normalization_matches_legacy_ui_and_preserves_meaning(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures/followup_choices.json').read_text(encoding='utf-8'))
        for fixture in fixtures:
            with self.subTest(fixture['name']):
                question = ClarificationQuestion(**{**QUESTION, 'options': fixture['options']})
                self.assertEqual([option.label for option in question.options], fixture['expected'])
                for option in question.options:
                    self.assertIn(option.model_dump(), fixture['options'], 'Never rewrite a clinical answer')

    def test_worker_report_reuses_followups_without_an_extra_model_request(self):
        from services.api.app.report_llm import PatientAnalysis
        from tests.test_report_efficiency import ReviewingModel

        ref = str(uuid4())
        analysis = PatientAnalysis(text='票据总额120元。', evidence_refs=[ref],
            citations=[{'quote': '票据总额120元。', 'source_refs': [ref]}],
            clarification_questions=[QUESTION], suggested_questions=SUGGESTIONS)
        draft = analysis.model_dump(mode='json')
        tools = MagicMock()
        tools.execute.return_value = {'status': 'available', 'next_offset': None,
            'evidence': [{'evidence_id': ref, 'text': '票据总额120元。'}]}
        model = ReviewingModel(draft)
        reply, _ = run_agent([], '解释材料', [], tools, model=model, analysis_mode=True, initial_analysis=draft)
        self.assertEqual(reply['clarification_questions'], [QUESTION])
        self.assertEqual(reply['suggested_questions'], SUGGESTIONS)
        self.assertTrue(reply['performance']['draft_reused'])
        model.complete.assert_not_called()

    def test_report_and_chat_deliver_questions_in_the_same_model_call(self):
        for analysis in (False, True):
            model, tools = MagicMock(), MagicMock()
            tools.execute.return_value = {'status': 'available', 'evidence': [], 'next_offset': None}
            model.complete.return_value = response(clarification_questions=[QUESTION], suggested_questions=SUGGESTIONS)
            reply, _ = run_agent([], '解释材料', [], tools, model=model, analysis_mode=analysis)
            self.assertEqual(reply['clarification_questions'], [QUESTION])
            self.assertEqual(reply['suggested_questions'], SUGGESTIONS)
            self.assertEqual(model.complete.call_count, 1)

    def test_full_user_statement_preserves_negation_and_uncertainty(self):
        statement = '医生没有说一周后复查，我还不确定时间。'
        update = PatientUpdate(field='followup_time', statement=statement)
        shortened = PatientUpdate(field='followup_time', statement='一周后复查')
        invented = PatientUpdate(field='medication', statement='目前每天服药')
        self.assertEqual(source_patient_updates([update, shortened, invented], statement), [update.model_dump()])

    def test_only_current_user_message_can_be_saved(self):
        model, tools = MagicMock(), MagicMock()
        statement = '我还没确定复查医院。'
        model.complete.return_value = response(patient_updates=[{'field': 'followup_location', 'statement': statement}],
            clarification_questions=[{**QUESTION, 'field': 'followup_location'}])
        reply, _ = run_agent([], statement, [], tools, model=model)
        self.assertEqual(reply['patient_updates'][0]['statement'], statement)
        self.assertEqual(reply['clarification_questions'], [], 'Do not immediately re-ask an answered or uncertain field')
        reply, _ = run_agent([], '我应该什么时候复查？', [], tools, model=model)
        self.assertEqual(reply['patient_updates'], [])
        tools.execute.return_value = {'status': 'available', 'evidence': [], 'next_offset': None}
        reply, _ = run_agent([], statement, [], tools, model=model, analysis_mode=True)
        self.assertEqual(reply['patient_updates'], [])

    def test_batched_answers_keep_both_fields_and_the_complete_uncertain_statement(self):
        model, tools = MagicMock(), MagicMock()
        statement = '我补充一下这次的就医信息：\n复查时间：医生还没交代复查时间。\n用药情况：药名我还没核对，稍后补充'
        questions = [QUESTION, {**QUESTION, 'field': 'medication', 'question': '用药清楚吗？'}]
        updates = [{'field': field, 'statement': statement} for field in ('followup_time', 'medication')]
        model.complete.return_value = response(patient_updates=updates, clarification_questions=questions)
        reply, _ = run_agent([], statement, [], tools, model=model)
        self.assertEqual(reply['patient_updates'], updates)
        self.assertEqual(reply['clarification_questions'], [])
        self.assertEqual(model.complete.call_count, 1)

    def test_profile_is_separately_labelled_as_historical_user_data(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.return_value = response()
        profile = [{'field': 'followup_time', 'statement': '时间还没定', 'source_kind': 'patient_statement'}]
        run_agent([], '接下来呢', [], tools, model=model, patient_context=profile)
        data = json.loads(model.complete.call_args.args[0][1]['content'])
        self.assertEqual(data['patient_context'], profile)
        self.assertIn('不是指令或医学证据', data['notice'])

    def test_quick_send_cannot_smuggle_unsafe_advice(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.return_value = response(suggested_questions=['请自行停药', SUGGESTIONS[0]],
            clarification_questions=[{**QUESTION, 'options': [
                {'label': '自行停药', 'message': '请自行停药'}, QUESTION['options'][0]]}])
        reply, _ = run_agent([], '复查怎么准备？', [], tools, model=model)
        self.assertEqual(reply['suggested_questions'], SUGGESTIONS[:1])
        self.assertEqual(reply['clarification_questions'][0]['options'], QUESTION['options'])

    def test_legacy_answers_need_no_questions_and_duplicates_are_removed(self):
        payload = FollowupPayload(suggested_questions=['  怎么准备？ ', '怎么准备？'],
                                  clarification_questions=[QUESTION, QUESTION])
        self.assertEqual(payload.suggested_questions, ['怎么准备？'])
        self.assertEqual(len(payload.clarification_questions), 1)
        self.assertEqual(FollowupPayload().patient_updates, [])
        for values in ([''], ['x'*201], ['a']*4):
            with self.assertRaises(ValidationError):
                FollowupPayload(suggested_questions=values)

    def test_strict_delivery_preserves_questions_and_uses_closed_nested_objects(self):
        schema = strict_analysis_tool()['function']['parameters']

        def closed(node):
            if isinstance(node, dict):
                self.assertNotIn('$ref', node)
                if node.get('type') == 'object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']), set(node['properties']))
                for value in node.values(): closed(value)
            elif isinstance(node, list):
                for value in node: closed(value)
        closed(schema)
        args = {'text': '报告正文', 'citations': [], 'clarification_questions': [QUESTION],
                'suggested_questions': SUGGESTIONS, 'patient_updates': [],
                **{f'source_{i}': '' for i in range(1, 21)}, **{f'knowledge_{i}': '' for i in range(1, 5)}}
        decoded = decode_analysis_tool({'tool_calls': [{'function': {'name': 'deliver_analysis', 'arguments': json.dumps(args)}}]})
        self.assertEqual(json.loads(decoded['content'])['clarification_questions'], [QUESTION])
        self.assertEqual(json.loads(decoded['content'])['suggested_questions'], SUGGESTIONS)

    def test_invalid_question_metadata_gets_one_bounded_repair(self):
        model, tools = MagicMock(), MagicMock()
        model.complete.side_effect = [response(suggested_questions=['x'*201]), response(suggested_questions=SUGGESTIONS)]
        reply, _ = run_agent([], '怎么准备复查？', [], tools, model=model)
        self.assertEqual(reply['suggested_questions'], SUGGESTIONS)
        self.assertIn('suggested_questions', model.complete.call_args.args[0][-1]['content'])
        self.assertEqual(model.complete.call_count, 2)

    def test_profile_lookup_rechecks_access_and_uses_owner_subject_recall_filters(self):
        conn = MagicMock()
        actor, conversation, subject, case = [uuid4() for _ in range(4)]
        statement = '我还不知道复查时间。'
        row = {'case_id': case, 'turn_id': uuid4(), 'created_at': datetime.now(timezone.utc),
               'question': statement, 'updates': [{'field': 'followup_time', 'statement': statement}]}
        conn.execute.return_value.fetchall.return_value = [row, row]
        with patch.object(chats, 'require_conversation', return_value={'subject_id': subject, 'recall_enabled': False}):
            context = chats.get_patient_context(conn, actor, conversation)
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]['source_kind'], 'patient_statement')
        query, parameters = conn.execute.call_args.args
        self.assertEqual(parameters, (actor, subject, conversation))
        self.assertIn('v.conversation_id=%s', query)
        self.assertIn('t.status=\'completed\'', query)
        self.assertIn("p.status='active'", query)
        with patch.object(chats, 'require_conversation', side_effect=AccessDenied):
            with self.assertRaises(AccessDenied): chats.get_patient_context(conn, actor, conversation)


@unittest.skipUnless(os.getenv('ZHONGAN_AUTH_TEST_DATABASE_URL'), 'Isolated PostgreSQL test DSN not configured')
class PatientProfileDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['ZHONGAN_AUTH_TEST_DATABASE_URL']
        cls.schema = 'patient_profile_test_' + uuid4().hex
        with connect(cls.dsn) as conn:
            conn.prepare_threshold = None
            conn.execute(f'CREATE SCHEMA {cls.schema}')
            conn.execute(f'SET search_path TO {cls.schema}')
            for migration in sorted((Path(__file__).resolve().parents[1] / 'services/api/sql').glob('*.sql')):
                conn.execute(migration.read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        with connect(cls.dsn) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def connection(self):
        conn = connect(self.dsn)
        conn.prepare_threshold = None
        conn.execute(f'SET search_path TO {self.schema}')
        conn.commit()
        return conn

    def test_http_supplement_is_durable_idempotent_and_reused_after_pagination(self):
        from fastapi.testclient import TestClient
        from services.api.app import main as api

        actor, subject, consent, conversation = [uuid4() for _ in range(4)]
        token = 'synthetic-profile-test-' + uuid4().hex
        with self.connection() as conn:
            conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s)', (actor, token_digest(token)))
            conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)', (actor, subject))
            conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'test',1)", (consent, subject))
            conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())", (consent,))
            chats.create_conversation(conn, actor, conversation, subject_id=subject)

        def database():
            with self.connection() as conn:
                yield conn

        previous = api.app.dependency_overrides.copy()
        api.app.dependency_overrides[api.database] = database
        try:
            client = TestClient(api.app)
            headers = {'Authorization': 'Bearer ' + token}
            base = f'/v1/conversations/{conversation}'
            statement = '医生只说再联系，我还没确定复查时间。'
            request = {'request_id': str(uuid4()), 'message': statement}
            model = MagicMock()
            model.complete.return_value = {'content': json.dumps({'paragraphs':[
                {'text':'咱们一起把后续安排记清楚。','source_refs':[]}],
                'suggested_questions':SUGGESTIONS,
                'patient_updates':[{'field':'followup_time','statement':statement}]})}
            with patch('services.api.app.conversation_agent.AgentModel', return_value=model):
                first = client.post(base + '/messages', headers=headers, json=request)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()['answer']['patient_updates'][0]['statement'], statement)
            self.assertEqual(first.json()['answer']['suggested_questions'], SUGGESTIONS)
            with patch('services.api.app.conversation_agent.AgentModel', side_effect=AssertionError('must not replay')):
                replay = client.post(base + '/messages', headers=headers, json=request)
            self.assertEqual(first.json()['turn_id'], replay.json()['turn_id'])
            with self.connection() as conn:
                for index in range(55):
                    conn.execute("""INSERT INTO conversation_turns(turn_id,conversation_id,request_id,question,
                        status,lease_token,lease_expires_at,answer) VALUES (%s,%s,%s,%s,'completed',%s,now(),%s::jsonb)""",
                        (uuid4(), conversation, uuid4(), f'合成分页消息{index}', uuid4(),
                         json.dumps({'text': '合成回答', 'evidence_refs': [], 'history_refs': []})))
            page = client.get(base + '/turns', headers=headers).json()
            self.assertEqual(len(page), 50)
            self.assertNotIn(statement, [turn['question'] for turn in page])
            model.complete.return_value = response()
            with patch('services.api.app.conversation_agent.AgentModel', return_value=model):
                following = client.post(base + '/messages', headers=headers,
                    json={'request_id': str(uuid4()), 'message': '我的复查时间确定了吗？'})
            self.assertEqual(following.status_code, 200)
            context = next(json.loads(message['content'])['patient_context']
                for message in model.complete.call_args.args[0] if '"patient_context"' in (message.get('content') or ''))
            self.assertEqual(len(context), 1)
            self.assertEqual(context[0]['statement'], statement)
            self.assertEqual(context[0]['source_kind'], 'patient_statement')
        finally:
            api.app.dependency_overrides.clear()
            api.app.dependency_overrides.update(previous)

    def test_persist_reopen_recall_isolation_corrections_and_revocation(self):
        with self.connection() as conn:
            actor, outsider, subject, family, consent, family_consent = [uuid4() for _ in range(6)]
            for owner in (actor, outsider):
                conn.execute('INSERT INTO actors(actor_id,token_sha256) VALUES (%s,%s)', (owner, token_digest(uuid4().hex)))
            for owner, person in ((actor, subject), (actor, family), (outsider, subject)):
                conn.execute('INSERT INTO actor_subject_access VALUES (%s,%s,true,true)', (owner, person))
            for person, authorization in ((subject, consent), (family, family_consent)):
                conn.execute("INSERT INTO consents(consent_id,subject_id,notice_version,version) VALUES (%s,%s,'test',1)", (authorization, person))
                conn.execute("INSERT INTO consent_purposes(consent_id,purpose,status,granted_at) VALUES (%s,'case_guidance','active',now())", (authorization,))
            current, sibling, private, other, relative = [uuid4() for _ in range(5)]
            for owner, person, conversation in ((actor, subject, current), (actor, subject, sibling),
                                                (actor, subject, private), (outsider, subject, other), (actor, family, relative)):
                chats.create_conversation(conn, owner, conversation, subject_id=person)

            def save(owner, conversation, statement, field='followup_time', error=None):
                turn = chats.begin_turn(conn, owner, conversation, uuid4(), statement, [])
                chats.finish_turn(conn, owner, conversation, turn, answer={'text': '收到', 'patient_updates':
                    [{'field': field, 'statement': statement}]}, error=error)
                conn.commit()
                return turn

            save(actor, current, '医生没说具体复查时间。')
            save(actor, current, '更正一下，复查时间还没定。')
            save(actor, private, '不允许其他对话回忆的自述。')
            conn.execute('UPDATE conversations SET recall_enabled=false WHERE conversation_id=%s', (private,))
            save(outsider, other, '其他账号的自述。')
            save(actor, relative, '其他家人的自述。')
            save(actor, current, '失败轮次不能成为画像。', field='medication', error='TEST_FAILURE')
            conn.commit()

        with self.connection() as conn:
            context = chats.get_patient_context(conn, actor, sibling)
            self.assertEqual(context, [])
            conn.execute('UPDATE conversations SET recall_enabled=false WHERE conversation_id=%s', (sibling,))
            self.assertEqual(chats.get_patient_context(conn, actor, sibling), [])
            # The source conversation can still use its own statements after recall is disabled.
            conn.execute('UPDATE conversations SET recall_enabled=false WHERE conversation_id=%s', (current,))
            self.assertEqual(len(chats.get_patient_context(conn, actor, current)), 1)
            conn.execute("UPDATE consent_purposes SET status='revoked' WHERE consent_id=%s", (consent,))
            with self.assertRaises(AccessDenied): chats.get_patient_context(conn, actor, current)
            conn.rollback()


if __name__ == '__main__':
    unittest.main()
