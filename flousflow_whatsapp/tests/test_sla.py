from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappSla(WhatsAppCommon):
    def _inbound(self):
        self._set_presence(self.agent, "online")
        return self.env["flousflow.whatsapp.connector.event"].ingest_inbound({
            "number_id": self.number.id, "external_message_id": "sla-1",
            "customer_phone_normalized": "+201099999999", "message_type": "text", "body": "Need help",
        })

    def test_inbound_starts_first_response_sla(self):
        conversation = self._inbound().conversation_id
        self.assertEqual(conversation.response_due_at, conversation.first_customer_message_at + timedelta(minutes=5))

    def test_first_outbound_stops_first_response_sla(self):
        conversation = self._inbound().conversation_id
        conversation.with_user(self.agent).acquire_write_lock()
        outbound = self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
            "conversation_id": conversation.id, "client_idempotency_key": "sla-reply", "body": "Handled",
        })
        self.assertFalse(conversation.first_response_at)
        outbound.sudo().mark_sent("wamid-outbound-1")
        self.assertTrue(conversation.first_response_at)
        self.assertFalse(conversation.response_due_at)

    def test_cron_marks_overdue_conversation_breached(self):
        conversation = self._inbound().conversation_id
        now = fields.Datetime.now()
        conversation.response_due_at = now - timedelta(seconds=1)
        updated_count = self.env["flousflow.whatsapp.conversation"].cron_update_sla(now=now)
        self.assertEqual(conversation.sla_state, "breached")
        self.assertEqual(updated_count, 1)
        self.assertEqual(
            self.env["flousflow.whatsapp.conversation"].cron_update_sla(now=now), 0
        )
