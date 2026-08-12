import base64
import json

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from .signing import ConnectorRequestError, verify_signed_request


class FlousflowWhatsappConnectorController(http.Controller):
    base_path = "/flousflow/whatsapp/v1"

    @staticmethod
    def _response(payload, status=200):
        return request.make_json_response(payload, status=status)

    def _signed_payload(self):
        raw_body = request.httprequest.get_data(cache=True)
        raw_limit = request.env["ir.config_parameter"].sudo().get_param(
            "flousflow_whatsapp.connector_max_body_bytes", str(15 * 1024 * 1024)
        )
        try:
            max_body_bytes = max(1024, min(int(raw_limit), 16 * 1024 * 1024))
        except (TypeError, ValueError):
            max_body_bytes = 15 * 1024 * 1024
        verify_signed_request(
            request.env, raw_body, request.httprequest.headers, max_body_bytes=max_body_bytes
        )
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorRequestError(400, "invalid_json", "Request body must be valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ConnectorRequestError(400, "invalid_payload", "Request payload must be a JSON object.")
        return payload

    @staticmethod
    def _number_for_session(session_key, require_inbound=False):
        number = request.env["flousflow.whatsapp.number"].sudo().search(
            [("connector_session_key", "=", session_key), ("active", "=", True)], limit=1
        )
        if not number:
            raise ConnectorRequestError(404, "unknown_session", "Connector session is unknown.")
        if require_inbound and not number.allow_inbound:
            raise ConnectorRequestError(403, "inbound_disabled", "Inbound messages are disabled for this number.")
        return number

    def _execute(self, callback):
        try:
            return callback()
        except ConnectorRequestError as exc:
            return self._response({"error": exc.code, "message": exc.message}, status=exc.status)
        except ValidationError as exc:
            return self._response({"error": "validation_error", "message": str(exc)}, status=422)

    @http.route(
        "/flousflow/whatsapp/v1/events", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def events(self):
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(
                payload.get("session_key"),
                require_inbound=(payload.get("direction") or "inbound") != "outbound",
            )
            inbound = dict(payload, number_id=number.id)
            inbound.pop("session_key", None)
            message = request.env["flousflow.whatsapp.connector.event"].sudo().ingest_inbound(inbound)
            return self._response({"message_id": message.id, "conversation_id": message.conversation_id.id})
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/presence", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def presence(self):
        """Report customer typing/stopped-typing so the inbox can show a hint."""
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(payload.get("session_key"))
            phone = payload.get("customer_phone_normalized")
            if not isinstance(phone, str) or not phone:
                raise ConnectorRequestError(422, "invalid_phone", "Customer phone is required.")
            typing = bool(payload.get("typing"))
            conversation = request.env["flousflow.whatsapp.conversation"].sudo().search([
                ("number_id", "=", number.id),
                ("customer_phone_normalized", "=", phone),
                ("state", "not in", ["closed", "spam", "blocked"]),
            ], limit=1)
            if not conversation:
                return self._response({"matched": False})
            conversation.set_customer_typing(typing)
            return self._response({"matched": True, "conversation_id": conversation.id, "typing": typing})
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/probe", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def probe(self):
        """Verify signed transport and session mapping without changing business data."""
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(payload.get("session_key"))
            try:
                pending_events = max(0, int(payload.get("pending_events") or 0))
            except (TypeError, ValueError):
                raise ConnectorRequestError(
                    422, "invalid_pending_events", "Pending event count must be an integer."
                )
            number.sudo().write({
                "connector_version": (payload.get("connector_version") or "")[:64] or False,
                "connector_last_probe_at": fields.Datetime.now(),
                "connector_pending_events": pending_events,
            })
            return self._response({"status": "ok", "number_id": number.id})
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/outbox/claim", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def claim_outbox(self):
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(payload.get("session_key"))
            messages = request.env["flousflow.whatsapp.message"].sudo().claim_outbox(
                number=number, limit=payload.get("limit", 20)
            )
            return self._response({"messages": [{
                "id": message.id,
                "client_idempotency_key": message.client_idempotency_key,
                "customer_phone": message.conversation_id.customer_phone_normalized,
                "message_type": message.message_type,
                "body": message.body or "",
                "attachment_id": message.attachment_id.id or None,
                "attempt_count": message.attempt_count,
                "voice_note": message.voice_note,
            } for message in messages]})
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/outbox/<int:message_id>/ack", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def acknowledge_outbox(self, message_id):
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(payload.get("session_key"))
            message = request.env["flousflow.whatsapp.message"].sudo().browse(message_id).exists()
            if not message or message.number_id != number or message.direction != "outbound":
                raise ConnectorRequestError(404, "unknown_message", "Outbound message was not found for this session.")
            state = payload.get("state")
            if state == "sent":
                message.mark_sent(payload.get("external_message_id"))
            elif state == "delivered":
                message.mark_delivered()
            elif state == "read":
                message.mark_read()
            elif state == "failed":
                message.mark_failed(
                    payload.get("error_code"),
                    payload.get("error_summary"),
                    retry_at=payload.get("retry_at"),
                    permanent=bool(payload.get("permanent")),
                )
            else:
                raise ConnectorRequestError(422, "invalid_state", "Acknowledgement state is invalid.")
            return self._response({"message_id": message.id, "state": message.state})
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/outbox/receipt", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def acknowledge_external_receipt(self):
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(payload.get("session_key"))
            state = payload.get("state")
            if state not in {"delivered", "read"}:
                raise ConnectorRequestError(422, "invalid_state", "Receipt state is invalid.")
            external_message_id = payload.get("external_message_id")
            if not isinstance(external_message_id, str) or not external_message_id:
                raise ConnectorRequestError(422, "invalid_message_id", "External message ID is required.")
            message = request.env["flousflow.whatsapp.message"].sudo().search([
                ("number_id", "=", number.id),
                ("direction", "=", "outbound"),
                ("external_message_id", "=", external_message_id),
            ], limit=1)
            if not message:
                return self._response({"matched": False, "state": state})
            if state == "read":
                message.mark_read()
            else:
                message.mark_delivered()
            return self._response({"matched": True, "message_id": message.id, "state": message.state})
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/attachments/<int:attachment_id>", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def attachment_content(self, attachment_id):
        def process():
            payload = self._signed_payload()
            number = self._number_for_session(payload.get("session_key"))
            message = request.env["flousflow.whatsapp.message"].sudo().search(
                [
                    ("attachment_id", "=", attachment_id),
                    ("number_id", "=", number.id),
                    ("direction", "=", "outbound"),
                ],
                limit=1,
            )
            if not message:
                raise ConnectorRequestError(404, "unknown_attachment", "Attachment was not found for this session.")
            attachment = message.attachment_id
            raw = attachment.raw or b""
            max_bytes = min(number.attachment_limit_mb, 10) * 1024 * 1024
            if len(raw) > max_bytes:
                raise ConnectorRequestError(413, "attachment_too_large", "Attachment exceeds the session limit.")
            return self._response({
                "name": attachment.name,
                "mimetype": attachment.mimetype or "application/octet-stream",
                "content_base64": base64.b64encode(raw).decode(),
            })
        return self._execute(process)

    @http.route(
        "/flousflow/whatsapp/v1/sessions/<string:session_key>/status", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def session_status(self, session_key):
        def process():
            payload = self._signed_payload()
            if payload.get("session_key") != session_key:
                raise ConnectorRequestError(401, "session_mismatch", "Signed session does not match the route.")
            number = self._number_for_session(session_key)
            state = payload.get("state")
            allowed_states = {"qr", "connecting", "connected", "reconnect", "disabled", "error"}
            if state not in allowed_states:
                raise ConnectorRequestError(422, "invalid_state", "Connector session state is invalid.")
            values = {"state": state, "last_error_summary": (payload.get("error_summary") or "")[:1000] or False}
            if state == "qr":
                qr_image = payload.get("qr_image")
                if not isinstance(qr_image, str) or len(qr_image) > 512 * 1024:
                    raise ConnectorRequestError(422, "invalid_qr", "QR image payload is invalid.")
                values["qr_image"] = qr_image
            elif state in {"connected", "disabled", "error"}:
                values["qr_image"] = False
            if state == "connected":
                values["last_connected_at"] = fields.Datetime.now()
            number.write(values)
            return self._response({"number_id": number.id, "state": number.state})
        return self._execute(process)
