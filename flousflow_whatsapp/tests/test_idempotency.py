import base64
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappIdempotency(WhatsAppCommon):
    def setUp(self):
        super().setUp()
        self.Event = self.env["flousflow.whatsapp.connector.event"]
        self.payload = {
            "number_id": self.number.id, "external_message_id": "wamid-1",
            "customer_phone_normalized": "+201012345678", "message_type": "text", "body": "Hello",
        }

    def test_duplicate_external_message_is_idempotent(self):
        first = self.Event.ingest_inbound(self.payload)
        second = self.Event.ingest_inbound(self.payload)
        self.assertEqual(first, second)
        self.assertEqual(self.env["flousflow.whatsapp.message"].search_count(
            [("external_message_id", "=", "wamid-1")]
        ), 1)

    def test_non_phone_chat_identifiers_are_rejected(self):
        for index, identifier in enumerate(("status", "120363145172827311"), start=1):
            with self.subTest(identifier=identifier), self.assertRaisesRegex(
                ValidationError, "valid customer phone number"
            ):
                self.Event.ingest_inbound(dict(
                    self.payload,
                    external_message_id=f"non-phone-{index}",
                    customer_phone_normalized=identifier,
                ))

    def test_status_story_with_alternate_customer_phone_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "status stories are not customer messages"):
            self.Event.ingest_inbound(dict(
                self.payload,
                external_message_id="status-with-author-phone",
                source_jid="status@broadcast",
            ))

    def test_inbound_video_keeps_metadata_only(self):
        message = self.Event.ingest_inbound(dict(
            self.payload, external_message_id="wamid-video", message_type="video"
        ))
        self.assertEqual(message.message_type, "video_metadata")
        self.assertFalse(message.attachment_id)

    def test_inbound_image_creates_scoped_attachment(self):
        raw = b"\x89PNG\r\n\x1a\nsmall-image"
        message = self.Event.ingest_inbound(dict(
            self.payload,
            external_message_id="wamid-image",
            message_type="image",
            filename="customer-image.png",
            mimetype="image/png",
            content_base64=base64.b64encode(raw).decode(),
        ))
        self.assertEqual(message.message_type, "image")
        self.assertEqual(bytes(message.attachment_id.raw), raw)
        self.assertEqual(message.attachment_id.res_model, message._name)
        self.assertEqual(message.attachment_id.res_id, message.id)

    def test_inbound_disguised_video_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "Video files are not allowed"):
            self.Event.ingest_inbound(dict(
                self.payload,
                external_message_id="wamid-hidden-video",
                message_type="document",
                filename="invoice.pdf",
                mimetype="application/pdf",
                content_base64=base64.b64encode(b"0000ftypisom").decode(),
            ))

    def test_duplicate_outbound_client_key_returns_same_message(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        payload = {"conversation_id": conversation.id, "client_idempotency_key": "client-1", "body": "Reply"}
        Message = self.env["flousflow.whatsapp.message"].with_user(self.agent)
        self.assertEqual(Message.queue_outbound(payload), Message.queue_outbound(payload))

    def test_recorded_audio_is_marked_as_voice_note(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        conversation.last_customer_message_at = fields.Datetime.now()
        message = self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "voice-note",
            "message_type": "audio",
            "voice_note": True,
            "filename": "voice.webm",
            "mimetype": "audio/webm",
            "content": base64.b64encode(b"\x1aE\xdf\xa3\x83\x81\x02voice").decode(),
        })
        self.assertTrue(message.voice_note)

    def test_outbound_is_blocked_outside_customer_service_window(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        conversation.last_customer_message_at = fields.Datetime.now() - timedelta(hours=25)
        with self.assertRaisesRegex(ValidationError, "24-hour customer service window"):
            self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
                "conversation_id": conversation.id,
                "client_idempotency_key": "outside-window",
                "body": "Late reply",
            })

    def test_supervisor_override_is_audited(self):
        conversation = self._new_conversation(self.supervisor, state="open")
        conversation.with_user(self.supervisor).acquire_write_lock()
        conversation.last_customer_message_at = fields.Datetime.now() - timedelta(hours=25)
        message = self.env["flousflow.whatsapp.message"].with_user(self.supervisor).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "window-override",
            "body": "Approved exception",
            "service_window_override": True,
            "service_window_override_reason": "Customer requested a follow-up by phone.",
        })
        self.assertTrue(message.service_window_override)
        self.assertTrue(self.env["flousflow.whatsapp.audit.event"].search([
            ("event_type", "=", "service_window_override"),
            ("conversation_id", "=", conversation.id),
        ]))

    def test_supervisor_can_manually_retry_failed_outbound(self):
        conversation = self._new_conversation(self.supervisor, state="open")
        conversation.with_user(self.supervisor).acquire_write_lock()
        conversation.last_customer_message_at = fields.Datetime.now()
        message = self.env["flousflow.whatsapp.message"].with_user(self.supervisor).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "manual-retry",
            "body": "Retry me",
        })
        message.sudo().mark_failed("network", "Temporary failure", permanent=True)
        message.with_user(self.supervisor).action_retry_failed()
        self.assertEqual(message.state, "queued")
        self.assertEqual(message.attempt_count, 0)
        self.assertTrue(message.next_attempt_at)
        self.assertTrue(self.env["flousflow.whatsapp.audit.event"].search([
            ("event_type", "=", "manual_retry"), ("conversation_id", "=", conversation.id),
        ]))

    def test_timezone_aware_backfill_timestamp_is_stored_as_naive_utc(self):
        message = self.Event.ingest_inbound(dict(
            self.payload,
            external_message_id="wamid-timezone",
            backfill=True,
            sent_at="2026-08-12T10:00:00+02:00",
        ))
        self.assertEqual(message.sent_at, datetime(2026, 8, 12, 8, 0, 0))

    def test_outbox_claim_is_number_scoped_and_single_claim(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        message = self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "claim-once",
            "body": "Queued reply",
        })
        claimed = self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5)
        self.assertEqual(claimed, message)
        self.assertEqual(message.state, "sending")
        self.assertEqual(message.attempt_count, 1)
        self.assertFalse(self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5))

    def test_transient_failure_is_claimed_only_after_retry_time(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        message = self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "retry-later",
            "body": "Retry later",
        })
        self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5)
        retry_at = fields.Datetime.now() + timedelta(minutes=5)
        message.mark_failed("network", "Temporary network error", retry_at=retry_at)
        self.assertFalse(self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5))
        message.next_attempt_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertEqual(
            self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5),
            message,
        )

    def test_permanent_failure_is_not_claimed_again(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        message = self.env["flousflow.whatsapp.message"].with_user(self.agent).queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": "permanent-failure",
            "body": "Do not retry",
        })
        self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5)
        message.mark_failed("policy", "Blocked permanently", permanent=True)
        self.assertFalse(message.next_attempt_at)
        self.assertFalse(self.env["flousflow.whatsapp.message"].claim_outbox(self.number, limit=5))
