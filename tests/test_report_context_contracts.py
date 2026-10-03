"""Contract-level tests for the frozen report-context snapshot (no database)."""
import unittest
from uuid import uuid4

from services.api.app.report_context import ChatContext, ContextSnapshot, UserTurn


def turn(text='关切'):
    return UserTurn(turn_id=uuid4(), text=text)


class TestUserTurn(unittest.TestCase):
    def test_rejects_empty_and_oversized_text(self):
        with self.assertRaises(Exception):
            UserTurn(turn_id=uuid4(), text='')
        with self.assertRaises(Exception):
            UserTurn(turn_id=uuid4(), text='x' * 8001)
        UserTurn(turn_id=uuid4(), text='x' * 8000)


class TestChatContext(unittest.TestCase):
    def test_rejects_more_than_twelve_turns(self):
        with self.assertRaises(Exception):
            ChatContext(conversation_id=uuid4(), actor_id=uuid4(), sharing_version=1,
                        anchor_turn_id=uuid4(), truncated=False, turns=[turn() for _ in range(13)])
        ctx = ChatContext(conversation_id=uuid4(), actor_id=uuid4(), sharing_version=1,
                          anchor_turn_id=uuid4(), truncated=True, turns=[turn() for _ in range(12)])
        self.assertTrue(ctx.truncated)


class TestContextSnapshot(unittest.TestCase):
    def test_version_is_fixed_and_chat_optional(self):
        with self.assertRaises(Exception):
            ContextSnapshot(consent_id=uuid4(), consent_version=1, policy_version='p',
                            prompt_version='v', version='care-context-v2')
        snap = ContextSnapshot(consent_id=uuid4(), consent_version=1, policy_version='p', prompt_version='v')
        self.assertIsNone(snap.chat)
        self.assertIsNone(snap.case_user_context)

    def test_policy_and_prompt_versions_are_required(self):
        with self.assertRaises(Exception):
            ContextSnapshot(consent_id=uuid4(), consent_version=1)


if __name__ == '__main__':
    unittest.main()
