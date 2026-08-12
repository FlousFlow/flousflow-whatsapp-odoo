from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestConversationRouting(WhatsAppCommon):
    def test_least_open_online_agent_is_selected(self):
        self._set_presence(self.agent, "online")
        self._set_presence(self.agent_b, "online")
        self._new_conversation(self.agent, state="open")
        conversation = self._new_conversation()

        conversation.assign_available_agent()

        self.assertEqual(conversation.assigned_user_id, self.agent_b)
        self.assertEqual(conversation.state, "open")

    def test_non_online_agent_is_not_selected(self):
        self._set_presence(self.agent, "busy")
        self._set_presence(self.agent_b, "online")
        conversation = self._new_conversation()

        conversation.assign_available_agent()

        self.assertEqual(conversation.assigned_user_id, self.agent_b)

    def test_no_online_agent_leaves_conversation_unassigned(self):
        self._set_presence(self.agent, "offline")
        self._set_presence(self.agent_b, "busy")
        conversation = self._new_conversation()

        conversation.assign_available_agent()

        self.assertFalse(conversation.assigned_user_id)
        self.assertEqual(conversation.state, "unassigned")

    def test_round_robin_breaks_equal_workload_tie(self):
        self._set_presence(self.agent, "online")
        self._set_presence(self.agent_b, "online")
        self.number.last_assigned_user_id = self.agent
        conversation = self._new_conversation()

        conversation.assign_available_agent()

        self.assertEqual(conversation.assigned_user_id, self.agent_b)

    def test_direct_deny_excludes_online_agent(self):
        self._set_presence(self.agent, "online")
        self._set_presence(self.agent_b, "offline")
        self.NumberMember.create(
            {
                "number_id": self.number.id,
                "user_id": self.agent.id,
                "access_mode": "deny",
            }
        )
        conversation = self._new_conversation()

        conversation.assign_available_agent()

        self.assertFalse(conversation.assigned_user_id)
