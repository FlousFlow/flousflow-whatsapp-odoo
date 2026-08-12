from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestOfflineReassignment(WhatsAppCommon):
    def setUp(self):
        super().setUp()
        self._set_presence(self.agent, "online")
        self._set_presence(self.agent_b, "online")
        self.conversation = self._new_conversation(self.agent, state="open")

    def test_non_online_assignee_gets_two_minute_deadline(self):
        self._set_presence(self.agent, "busy")
        now = fields.Datetime.now()

        self.Conversation.update_non_online_grace(now=now)

        self.assertEqual(
            self.conversation.assignment_release_at,
            now + timedelta(minutes=2),
        )

    def test_returning_online_cancels_release_deadline(self):
        self.conversation.assignment_release_at = fields.Datetime.now() + timedelta(minutes=1)
        self._set_presence(self.agent, "online")

        self.Conversation.update_non_online_grace()

        self.assertFalse(self.conversation.assignment_release_at)

    def test_due_conversation_reassigns_to_online_agent(self):
        self._set_presence(self.agent, "offline")
        self.conversation.assignment_release_at = fields.Datetime.now() - timedelta(seconds=1)

        self.Conversation.process_non_online_grace()

        self.assertEqual(self.conversation.assigned_user_id, self.agent_b)
        self.assertEqual(self.conversation.state, "open")
        self.assertFalse(self.conversation.assignment_release_at)

    def test_due_conversation_releases_active_lock(self):
        lock = self.conversation.with_user(self.agent).acquire_write_lock()
        self._set_presence(self.agent, "offline")
        self.conversation.assignment_release_at = fields.Datetime.now() - timedelta(seconds=1)

        self.Conversation.process_non_online_grace()

        self.assertTrue(lock.released_at)
        self.assertEqual(lock.release_reason, "offline")
