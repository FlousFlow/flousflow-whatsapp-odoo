from odoo.exceptions import AccessError

from .common import WhatsAppCommon


class TestWhatsappInboxUnread(WhatsAppCommon):
    def _ingest(self, external_id="unread-1", **overrides):
        payload = {
            "number_id": self.number.id,
            "external_message_id": external_id,
            "customer_phone_normalized": "+201088888881",
            "customer_name": "Unread Customer",
            "direction": "inbound",
            "message_type": "text",
            "body": "Hello",
        }
        payload.update(overrides)
        return self.env["flousflow.whatsapp.connector.event"].ingest_inbound(payload)

    def test_inbound_message_increments_unread_count(self):
        message = self._ingest()
        self.assertEqual(message.conversation_id.unread_count, 1)

    def test_inbound_messages_accumulate_unread(self):
        self._ingest(external_id="unread-1")
        self._ingest(external_id="unread-2")
        self._ingest(external_id="unread-3")
        self.assertEqual(
            self.env["flousflow.whatsapp.conversation"].search(
                [("customer_phone_normalized", "=", "+201088888881")]
            ).unread_count,
            3,
        )

    def test_open_conversation_does_not_increment_unread(self):
        """When an agent holds an active write lock, new inbound is not unread."""
        message = self._ingest(external_id="unread-1")
        conversation = message.conversation_id
        conversation.write({"assigned_user_id": self.agent.id, "state": "open"})
        conversation.acquire_write_lock()
        self._ingest(external_id="unread-2")
        self.assertEqual(conversation.unread_count, 1)

    def test_mark_seen_clears_unread(self):
        conversation = self._ingest().conversation_id
        self.assertEqual(conversation.unread_count, 1)
        conversation.mark_seen()
        self.assertEqual(conversation.unread_count, 0)


class TestWhatsappHistoryBackfill(WhatsAppCommon):
    def _ingest_backfill(self, external_id="backfill-1", **overrides):
        payload = {
            "number_id": self.number.id,
            "external_message_id": external_id,
            "customer_phone_normalized": "+201055555555",
            "customer_name": "Old Customer",
            "direction": "inbound",
            "message_type": "text",
            "body": "Old message",
            "backfill": True,
            "sent_at": "2026-01-01 10:00:00",
        }
        payload.update(overrides)
        return self.env["flousflow.whatsapp.connector.event"].ingest_inbound(payload)

    def test_backfill_does_not_increment_unread(self):
        message = self._ingest_backfill()
        self.assertEqual(message.conversation_id.unread_count, 0)
        self.assertEqual(message.sent_at, self.env.cr.mogrify(
            "%s", ["2026-01-01 10:00:00"]
        ).decode().strip("'"))

    def test_backfill_keeps_conversation_unassigned_without_sla(self):
        message = self._ingest_backfill()
        conversation = message.conversation_id
        self.assertEqual(conversation.state, "unassigned")
        self.assertFalse(conversation.assigned_user_id)
        self.assertFalse(conversation.first_customer_message_at)
        self.assertFalse(conversation.response_due_at)

    def test_live_message_after_backfill_is_actionable(self):
        self._ingest_backfill()
        live = self.env["flousflow.whatsapp.connector.event"].ingest_inbound({
            "number_id": self.number.id,
            "external_message_id": "live-1",
            "customer_phone_normalized": "+201055555555",
            "customer_name": "Old Customer",
            "direction": "inbound",
            "message_type": "text",
            "body": "Live now",
        })
        conversation = live.conversation_id
        self.assertEqual(conversation.unread_count, 1)
        self.assertTrue(conversation.first_customer_message_at)
        self.assertTrue(conversation.response_due_at)


class TestWhatsappInboxTyping(WhatsAppCommon):
    def _make_conversation(self):
        conversation = self.Conversation.create({
            "company_id": self.company.id,
            "number_id": self.number.id,
            "team_id": self.team.id,
            "customer_phone_normalized": "+201077777777",
            "state": "unassigned",
        })
        return conversation

    def test_set_customer_typing_true_then_false(self):
        conversation = self._make_conversation()
        conversation.set_customer_typing(True)
        self.assertTrue(conversation.customer_typing)
        conversation.set_customer_typing(False)
        self.assertFalse(conversation.customer_typing)


class TestWhatsappInboxClose(WhatsAppCommon):
    def _make_conversation(self, assigned=False):
        conversation = self.Conversation.create({
            "company_id": self.company.id,
            "number_id": self.number.id,
            "team_id": self.team.id,
            "customer_phone_normalized": "+201066666666",
            "state": "unassigned",
        })
        if assigned:
            conversation.write({
                "assigned_user_id": self.agent.id,
                "state": "open",
            })
        return conversation

    def test_close_from_inbox_requires_access(self):
        conversation = self._make_conversation(assigned=True)
        with self.assertRaises(AccessError):
            conversation.with_user(self.agent_b).action_close_from_inbox()

    def test_close_from_inbox_by_assigned_agent(self):
        conversation = self._make_conversation(assigned=True)
        conversation.with_user(self.agent).action_close_from_inbox()
        self.assertEqual(conversation.state, "closed")
        self.assertEqual(conversation.unread_count, 0)

    def test_close_from_inbox_unassigned_by_any_agent(self):
        conversation = self._make_conversation(assigned=False)
        conversation.with_user(self.agent).action_close_from_inbox()
        self.assertEqual(conversation.state, "closed")

    def test_close_releases_active_lock(self):
        conversation = self._make_conversation(assigned=True)
        conversation.with_user(self.agent).acquire_write_lock()
        self.assertTrue(conversation.lock_ids.filtered(lambda lock: not lock.released_at))
        conversation.with_user(self.agent).action_close_from_inbox()
        self.assertFalse(conversation.lock_ids.filtered(lambda lock: not lock.released_at))
