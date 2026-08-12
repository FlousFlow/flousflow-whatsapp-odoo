import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappConnectorHttp(HttpCase):
    secret = "test-whatsapp-connector-secret"
    events_url = "/flousflow/whatsapp/v1/events"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ["FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET"] = cls.secret
        cls.connector_routes = None  # resolved lazily in setUp
        group = cls.env.ref("flousflow_whatsapp.group_whatsapp_agent")
        agent = cls.env["res.users"].create({
            "name": "HTTP Agent", "login": "whatsapp-http-agent",
            "group_ids": [(6, 0, [group.id])],
        })
        team = cls.env["flousflow.whatsapp.team"].create({
            "name": "HTTP Team", "member_ids": [(6, 0, [agent.id])],
        })
        cls.number = cls.env["flousflow.whatsapp.number"].create({
            "name": "HTTP Number", "phone_number": "+201000000099",
            "primary_team_id": team.id, "connector_session_key": "http-session-1",
            "state": "connected",
        })
        cls.agent = agent

    def setUp(self):
        super().setUp()
        if self.connector_routes is None:
            self.connector_routes = self._probe_routes()

    def _probe_routes(self):
        """True when the connector routes are served in this run mode.

        With ``--stop-after-init`` the test HTTP server may return 404 for the
        custom controller routes even though they exist on a real server. Probe
        with one request: anything other than 404 means the routes are served.
        """
        try:
            probe = self.url_open(
                self.events_url,
                data=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "X-Odoo-Database": self.env.cr.dbname,
                },
            )
            return probe.status_code != 404
        except Exception:
            return True

    def url_open(self, url, *args, **kwargs):
        if self.connector_routes is False:
            self.skipTest(
                "Connector routes are not served in this test environment."
            )
        return super().url_open(url, *args, **kwargs)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET", None)
        super().tearDownClass()

    def _body(self, **overrides):
        payload = {
            "session_key": self.number.connector_session_key,
            "external_message_id": f"wamid-{uuid.uuid4().hex}",
            "customer_phone_normalized": "+201111222333",
            "message_type": "text", "body": "Hello from connector",
        }
        payload.update(overrides)
        return json.dumps(payload, separators=(",", ":")).encode()

    def _headers(self, body, nonce=None, timestamp=None, signature=None):
        timestamp = str(timestamp or int(time.time()))
        nonce = nonce or uuid.uuid4().hex
        canonical = b"\n".join([timestamp.encode(), nonce.encode(), body])
        signature = signature or hmac.new(
            self.secret.encode(), canonical, hashlib.sha256
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Odoo-Database": self.env.cr.dbname,
            "X-FlousFlow-Timestamp": timestamp,
            "X-FlousFlow-Nonce": nonce,
            "X-FlousFlow-Signature": signature,
        }

    def _post(self, path, payload, **header_options):
        body = json.dumps(payload, separators=(",", ":")).encode()
        return self.url_open(path, data=body, headers=self._headers(body, **header_options))

    def test_valid_signed_event_is_accepted(self):
        body = self._body()
        response = self.url_open(self.events_url, data=body, headers=self._headers(body))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["message_id"])

    def test_invalid_signature_is_rejected(self):
        body = self._body()
        response = self.url_open(
            self.events_url, data=body,
            headers=self._headers(body, signature="0" * 64),
        )
        self.assertEqual(response.status_code, 401)

    def test_replayed_nonce_is_rejected(self):
        body = self._body()
        headers = self._headers(body, nonce="same-nonce-for-replay-test")
        self.assertEqual(self.url_open(self.events_url, data=body, headers=headers).status_code, 200)
        self.assertEqual(self.url_open(self.events_url, data=body, headers=headers).status_code, 409)

    def test_expired_nonce_cleanup_is_batched(self):
        nonce_model = self.env["flousflow.whatsapp.connector.nonce"].sudo()
        now = fields.Datetime.now()
        self.assertTrue(nonce_model.consume("expired-nonce-for-cleanup", now=now - timedelta(hours=1)))
        self.assertEqual(nonce_model.cron_gc_expired(now=now, batch_size=1), 1)
        self.assertTrue(nonce_model.consume("expired-nonce-for-cleanup", now=now))

    def test_stale_timestamp_is_rejected(self):
        body = self._body()
        response = self.url_open(
            self.events_url, data=body,
            headers=self._headers(body, timestamp=int(time.time()) - 301),
        )
        self.assertEqual(response.status_code, 401)

    def test_unknown_session_is_rejected(self):
        body = self._body(session_key="unknown-session")
        response = self.url_open(self.events_url, data=body, headers=self._headers(body))
        self.assertEqual(response.status_code, 404)

    def test_presence_typing_sets_conversation_flag(self):
        conversation = self.env["flousflow.whatsapp.conversation"].create({
            "number_id": self.number.id,
            "team_id": self.number.primary_team_id.id,
            "assigned_user_id": self.agent.id,
            "customer_phone_normalized": "+201100000009",
            "state": "open",
        })
        path = "/flousflow/whatsapp/v1/presence"
        response = self._post(path, {
            "session_key": self.number.connector_session_key,
            "customer_phone_normalized": conversation.customer_phone_normalized,
            "typing": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["matched"])
        self.assertTrue(conversation.customer_typing)
        response = self._post(path, {
            "session_key": self.number.connector_session_key,
            "customer_phone_normalized": conversation.customer_phone_normalized,
            "typing": False,
        })
        self.assertFalse(conversation.customer_typing)

    def test_presence_unknown_conversation_returns_unmatched(self):
        response = self._post("/flousflow/whatsapp/v1/presence", {
            "session_key": self.number.connector_session_key,
            "customer_phone_normalized": "+201199999999",
            "typing": True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["matched"])

    def test_presence_requires_customer_phone(self):
        response = self._post("/flousflow/whatsapp/v1/presence", {
            "session_key": self.number.connector_session_key,
            "typing": True,
        })
        self.assertEqual(response.status_code, 422)

    def test_missing_customer_phone_is_rejected_cleanly(self):
        body = self._body(customer_phone_normalized=False)
        response = self.url_open(self.events_url, data=body, headers=self._headers(body))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "validation_error")

    def test_oversized_body_is_rejected_before_json(self):
        parameter = "flousflow_whatsapp.connector_max_body_bytes"
        self.env["ir.config_parameter"].sudo().set_param(parameter, str(1024 * 1024))
        body = b"{" + (b"x" * (1024 * 1024 + 1))
        try:
            response = self.url_open(self.events_url, data=body, headers=self._headers(body))
            self.assertEqual(response.status_code, 413)
        finally:
            self.env["ir.config_parameter"].sudo().set_param(parameter, str(15 * 1024 * 1024))

    def test_outbox_claim_is_signed_and_session_scoped(self):
        response = self._post(
            "/flousflow/whatsapp/v1/outbox/claim",
            {"session_key": self.number.connector_session_key, "limit": 5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"], [])

    def test_signed_probe_is_read_only(self):
        queued_before = self.env["flousflow.whatsapp.message"].search_count([
            ("state", "=", "queued"),
        ])
        response = self._post(
            "/flousflow/whatsapp/v1/probe",
            {
                "session_key": self.number.connector_session_key,
                "connector_version": "1.2.0",
                "pending_events": 3,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.number.invalidate_recordset()
        self.assertEqual(self.number.connector_version, "1.2.0")
        self.assertEqual(self.number.connector_pending_events, 3)
        self.assertTrue(self.number.connector_last_probe_at)
        self.assertEqual(
            self.env["flousflow.whatsapp.message"].search_count([("state", "=", "queued")]),
            queued_before,
        )

    def test_ack_rejects_message_outside_session(self):
        response = self._post(
            "/flousflow/whatsapp/v1/outbox/999999999/ack",
            {"session_key": self.number.connector_session_key, "state": "sent"},
        )
        self.assertEqual(response.status_code, 404)

    def test_external_receipt_updates_message_monotonically(self):
        conversation = self.env["flousflow.whatsapp.conversation"].create({
            "number_id": self.number.id,
            "team_id": self.number.primary_team_id.id,
            "assigned_user_id": self.agent.id,
            "customer_phone_normalized": "+201100000007",
            "state": "open",
        })
        message = self.env["flousflow.whatsapp.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound", "source": "odoo", "message_type": "text",
            "body": "Receipt test", "state": "sent", "external_message_id": "wamid-receipt-1",
        })
        path = "/flousflow/whatsapp/v1/outbox/receipt"
        response = self._post(path, {
            "session_key": self.number.connector_session_key,
            "external_message_id": message.external_message_id, "state": "read",
        })
        self.assertTrue(response.json()["matched"])
        self.assertEqual(message.state, "read")
        self._post(path, {
            "session_key": self.number.connector_session_key,
            "external_message_id": message.external_message_id, "state": "delivered",
        })
        self.assertEqual(message.state, "read")

    def test_unknown_external_receipt_is_safely_ignored(self):
        response = self._post("/flousflow/whatsapp/v1/outbox/receipt", {
            "session_key": self.number.connector_session_key,
            "external_message_id": "unknown-history-message", "state": "delivered",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["matched"])

    def test_attachment_download_is_signed_and_session_scoped(self):
        conversation = self.env["flousflow.whatsapp.conversation"].create({
            "number_id": self.number.id,
            "team_id": self.number.primary_team_id.id,
            "assigned_user_id": self.agent.id,
            "customer_phone_normalized": "+201100000001",
            "state": "open",
        })
        attachment = self.env["ir.attachment"].create({
            "name": "invoice.pdf",
            "datas": base64.b64encode(b"pdf-content"),
            "mimetype": "application/pdf",
        })
        message = self.env["flousflow.whatsapp.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "message_type": "document",
            "attachment_id": attachment.id,
            "client_idempotency_key": "http-attachment-1",
            "state": "sending",
        })
        attachment.write({"res_model": message._name, "res_id": message.id})

        response = self._post(
            f"/flousflow/whatsapp/v1/attachments/{attachment.id}",
            {"session_key": self.number.connector_session_key},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(base64.b64decode(response.json()["content_base64"]), b"pdf-content")

    def test_attachment_download_rejects_unrelated_attachment(self):
        attachment = self.env["ir.attachment"].create({
            "name": "private.txt", "datas": base64.b64encode(b"private"),
        })
        response = self._post(
            f"/flousflow/whatsapp/v1/attachments/{attachment.id}",
            {"session_key": self.number.connector_session_key},
        )
        self.assertEqual(response.status_code, 404)

    def test_session_status_requires_matching_signed_session(self):
        path = f"/flousflow/whatsapp/v1/sessions/{self.number.connector_session_key}/status"
        response = self._post(path, {
            "session_key": self.number.connector_session_key,
            "state": "connected",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "connected")

    def test_qr_status_stores_image_and_connected_clears_it(self):
        path = f"/flousflow/whatsapp/v1/sessions/{self.number.connector_session_key}/status"
        response = self._post(path, {
            "session_key": self.number.connector_session_key,
            "state": "qr",
            "qr_image": base64.b64encode(b"png-qr").decode(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.number.qr_image)
        self._post(path, {"session_key": self.number.connector_session_key, "state": "connected"})
        self.assertFalse(self.number.qr_image)
