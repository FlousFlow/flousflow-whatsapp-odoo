from unittest.mock import patch

from odoo.exceptions import AccessError

from .common import WhatsAppCommon


class TestWhatsappMessageSync(WhatsAppCommon):
    def _ingest(self, **overrides):
        payload = {
            "number_id": self.number.id,
            "external_message_id": "sync-message-1",
            "customer_phone_normalized": "+201099999991",
            "customer_name": "Ahmed WhatsApp",
            "direction": "inbound",
            "message_type": "text",
            "body": "Hello",
        }
        payload.update(overrides)
        return self.env["flousflow.whatsapp.connector.event"].ingest_inbound(payload)

    def test_unknown_inbound_number_does_not_create_contact(self):
        before = self.env["res.partner"].search_count([])
        message = self._ingest()
        self.assertFalse(message.conversation_id.partner_id)
        self.assertEqual(message.conversation_id.customer_display_name, "Ahmed WhatsApp")
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_existing_real_partner_name_is_preserved(self):
        self.env["res.partner"].create({
            "name": "Approved Customer Name",
            "phone": "+201099999991",
            "company_id": self.company.id,
        })
        message = self._ingest(customer_name="Different WhatsApp Name")
        self.assertEqual(message.conversation_id.partner_id.name, "Approved Customer Name")

    def test_existing_numeric_conversation_partner_gets_profile_name(self):
        partner = self.env["res.partner"].create({
            "name": "+201099999991",
            "phone": "+201099999991",
            "company_id": self.company.id,
        })
        self.Conversation.create({
            "company_id": self.company.id,
            "number_id": self.number.id,
            "team_id": self.team.id,
            "partner_id": partner.id,
            "customer_phone_normalized": "+201099999991",
            "state": "unassigned",
        })
        self._ingest(customer_name="Existing Chat Name")
        self.assertEqual(partner.name, "Existing Chat Name")

    def test_existing_unknown_conversation_stores_new_profile_name_without_contact(self):
        conversation = self.Conversation.create({
            "company_id": self.company.id,
            "number_id": self.number.id,
            "team_id": self.team.id,
            "customer_phone_normalized": "+201099999991",
            "state": "unassigned",
        })
        before = self.env["res.partner"].search_count([])
        self._ingest(customer_name="Updated WhatsApp Name")
        self.assertFalse(conversation.partner_id)
        self.assertEqual(conversation.customer_display_name, "Updated WhatsApp Name")
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_linked_device_reply_is_recorded_as_external_outbound(self):
        message = self._ingest(direction="outbound", customer_name=False)
        self.assertEqual(message.direction, "outbound")
        self.assertEqual(message.source, "whatsapp_device")
        self.assertFalse(message.author_user_id)

    def test_linked_device_reply_releases_active_odoo_composer_lock(self):
        conversation = self._new_conversation(self.agent, state="open")
        lock = conversation.with_user(self.agent).acquire_write_lock()
        self._ingest(
            direction="outbound",
            customer_name=False,
            customer_phone_normalized=conversation.customer_phone_normalized,
        )
        self.assertTrue(lock.released_at)
        self.assertEqual(lock.release_reason, "external_reply")

    def test_linked_device_reply_does_not_unassign_the_agent(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        self._ingest(
            direction="outbound",
            customer_name=False,
            customer_phone_normalized=conversation.customer_phone_normalized,
        )
        self.assertEqual(conversation.assigned_user_id, self.agent)
        self.assertEqual(conversation.state, "open")

    def test_odoo_cannot_send_until_agent_reviews_external_reply(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        self._ingest(
            direction="outbound",
            customer_name=False,
            customer_phone_normalized=conversation.customer_phone_normalized,
        )
        with self.assertRaisesRegex(AccessError, "acquire the conversation lock"):
            self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
                "conversation_id": conversation.id,
                "client_idempotency_key": "blocked-after-phone-reply",
                "body": "Stale draft",
            })
        conversation.with_user(self.agent).acquire_write_lock()
        message = self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "reviewed-after-phone-reply",
            "body": "Reviewed reply",
        })
        self.assertEqual(message.state, "queued")

    def test_message_ingestion_sends_targeted_realtime_notification(self):
        partner_model = type(self.agent.partner_id)
        with patch.object(partner_model, "_bus_send", autospec=True) as bus_send:
            message = self._ingest()
        self.assertTrue(bus_send.called)
        notification_types = [call.args[1] for call in bus_send.call_args_list]
        self.assertIn("flousflow_whatsapp.message", notification_types)
        self.assertEqual(message.state, "received")

    def test_realtime_event_identifies_direct_phone_reply(self):
        partner_model = type(self.agent.partner_id)
        with patch.object(partner_model, "_bus_send", autospec=True) as bus_send:
            self._ingest(direction="outbound", customer_name=False)
        payloads = [call.args[2] for call in bus_send.call_args_list]
        self.assertTrue(any(
            payload.get("direction") == "outbound"
            and payload.get("source") == "whatsapp_device"
            for payload in payloads
        ))

    def test_outbox_ack_merges_an_early_linked_device_echo(self):
        echo = self._ingest(direction="outbound", customer_name=False)
        conversation = echo.conversation_id
        queued = self.env["flousflow.whatsapp.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "source": "odoo",
            "message_type": "text",
            "body": "Hello",
            "client_idempotency_key": "echo-race-1",
            "state": "sending",
        })
        queued.mark_sent("sync-message-1")
        messages = self.env["flousflow.whatsapp.message"].search([
            ("number_id", "=", self.number.id),
            ("external_message_id", "=", "sync-message-1"),
        ])
        self.assertEqual(messages, queued)
        self.assertEqual(messages.source, "odoo")
