from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestConversationLocking(WhatsAppCommon):
    def setUp(self):
        super().setUp()
        self._set_presence(self.agent, "online")
        self._set_presence(self.agent_b, "online")
        self.conversation = self._new_conversation(self.agent, state="open")

    def test_assignee_acquires_and_renews_lock(self):
        lock = self.conversation.with_user(self.agent).acquire_write_lock()
        renewed = self.conversation.with_user(self.agent).heartbeat_write_lock()
        self.assertEqual(lock, renewed)
        self.assertEqual(lock.owner_user_id, self.agent)
        self.assertFalse(lock.released_at)

    def test_second_user_cannot_acquire_active_lock(self):
        self.conversation.with_user(self.agent).acquire_write_lock()
        with self.assertRaises(UserError):
            self.conversation.with_user(self.agent_b).acquire_write_lock()

    def test_non_assignee_cannot_acquire_unlocked_conversation(self):
        with self.assertRaises(AccessError):
            self.conversation.with_user(self.agent_b).acquire_write_lock()

    def test_owner_can_release_lock(self):
        lock = self.conversation.with_user(self.agent).acquire_write_lock()
        self.conversation.with_user(self.agent).release_write_lock("close")
        self.assertTrue(lock.released_at)
        self.assertEqual(lock.release_reason, "close")

    def test_lock_info_is_read_only_for_other_authorized_agent(self):
        self.conversation.with_user(self.agent).acquire_write_lock()
        info = self.conversation.with_user(self.agent_b).get_write_lock_info()
        self.assertFalse(info["owned_by_me"])
        self.assertEqual(info["owner_name"], self.agent.name)

    def test_agent_can_claim_unassigned_conversation(self):
        conversation = self._new_conversation()
        info = conversation.with_user(self.agent).claim_and_acquire_write_lock()
        self.assertEqual(conversation.assigned_user_id, self.agent)
        self.assertEqual(conversation.state, "open")
        self.assertTrue(info["owned_by_me"])

    def test_agent_cannot_claim_conversation_assigned_to_another_user(self):
        with self.assertRaises(UserError):
            self.conversation.with_user(self.agent_b).claim_and_acquire_write_lock()
