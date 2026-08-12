import base64

from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappMessage(models.Model):
    _name = "flousflow.whatsapp.message"
    _description = "Flous Flow WhatsApp Message"
    _order = "create_date, id"
    _check_company_auto = True

    conversation_id = fields.Many2one(
        "flousflow.whatsapp.conversation", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(related="conversation_id.company_id", store=True, index=True)
    number_id = fields.Many2one(related="conversation_id.number_id", store=True, index=True)
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")], required=True, index=True
    )
    source = fields.Selection(
        [
            ("customer", "Customer"),
            ("odoo", "Odoo"),
            ("whatsapp_device", "WhatsApp Device"),
        ],
        required=True,
        default="customer",
        index=True,
    )
    message_type = fields.Selection(
        [
            ("text", "Text"), ("image", "Image"), ("document", "Document"),
            ("audio", "Audio"), ("video_metadata", "Video Metadata"),
            ("system", "System"),
        ], required=True, default="text", index=True,
    )
    body = fields.Text()
    attachment_id = fields.Many2one("ir.attachment", ondelete="restrict")
    attachment_name = fields.Char(related="attachment_id.name", readonly=True)
    attachment_mimetype = fields.Char(related="attachment_id.mimetype", readonly=True)
    attachment_size = fields.Integer(related="attachment_id.file_size", readonly=True)
    voice_note = fields.Boolean(
        copy=False,
        help="Send an audio attachment as a native WhatsApp push-to-talk voice note.",
    )
    service_window_override = fields.Boolean(copy=False, readonly=True)
    service_window_override_reason = fields.Text(copy=False, readonly=True)
    external_message_id = fields.Char(index=True, copy=False)
    client_idempotency_key = fields.Char(index=True, copy=False)
    author_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    state = fields.Selection(
        [
            ("queued", "Queued"), ("sending", "Sending"), ("sent", "Sent"),
            ("delivered", "Delivered"), ("read", "Read"), ("failed", "Failed"),
            ("received", "Received"),
        ], required=True, index=True,
    )
    error_code = fields.Char(copy=False)
    error_summary = fields.Text(copy=False)
    sent_at = fields.Datetime(copy=False)
    delivered_at = fields.Datetime(copy=False)
    read_at = fields.Datetime(copy=False)
    attempt_count = fields.Integer(default=0, copy=False)
    next_attempt_at = fields.Datetime(index=True, copy=False)

    _external_message_unique = models.Constraint(
        "UNIQUE(number_id, external_message_id)",
        "This external WhatsApp message was already processed.",
    )
    _client_key_unique = models.Constraint(
        "UNIQUE(company_id, client_idempotency_key)",
        "This outbound WhatsApp request was already queued.",
    )

    @api.model
    def queue_outbound(self, payload):
        conversation = self.env["flousflow.whatsapp.conversation"].browse(
            payload.get("conversation_id")
        ).exists()
        if not conversation:
            raise ValidationError(_("The WhatsApp conversation no longer exists."))
        self.env.cr.execute(
            "SELECT id FROM flousflow_whatsapp_conversation WHERE id = %s FOR UPDATE",
            [conversation.id],
        )
        conversation.invalidate_recordset(["assigned_user_id", "state", "lock_ids"])
        if not conversation.number_id.allow_outbound:
            raise AccessError(_("Outbound WhatsApp messages are disabled for this number."))
        if not conversation.number_id.user_can_access(self.env.user):
            raise AccessError(_("You are not allowed to use this WhatsApp number."))
        if conversation.assigned_user_id != self.env.user:
            raise AccessError(_("Only the assigned agent can send in this conversation."))
        active_lock = conversation.lock_ids.filtered(
            lambda lock: not lock.released_at and lock.expires_at > fields.Datetime.now()
        )
        if not active_lock or active_lock.owner_user_id != self.env.user:
            raise AccessError(_("Open the composer and acquire the conversation lock before sending."))
        key = payload.get("client_idempotency_key")
        if not key:
            raise ValidationError(_("An outbound idempotency key is required."))
        existing = self.sudo().search(
            [("company_id", "=", conversation.company_id.id), ("client_idempotency_key", "=", key)],
            limit=1,
        )
        if existing:
            return existing
        override = bool(payload.get("service_window_override"))
        override_reason = (payload.get("service_window_override_reason") or "").strip()
        number = conversation.number_id
        if number.enforce_service_window and conversation.last_customer_message_at:
            deadline = conversation.last_customer_message_at + timedelta(
                hours=number.service_window_hours
            )
            if fields.Datetime.now() > deadline:
                if not override:
                    raise ValidationError(_(
                        "The %(hours)s-hour customer service window has expired. "
                        "A supervisor override is required.",
                        hours=number.service_window_hours,
                    ))
                if not self.env.user.has_group(
                    "flousflow_whatsapp.group_whatsapp_supervisor"
                ):
                    raise AccessError(_("Only a WhatsApp supervisor can override the service window."))
                if len(override_reason) < 10:
                    raise ValidationError(_("Enter a clear override reason of at least 10 characters."))
            else:
                override = False
                override_reason = ""
        else:
            override = False
            override_reason = ""
        attachment = False
        content = payload.get("content")
        mimetype = payload.get("mimetype")
        filename = payload.get("filename")
        if content is not None:
            raw = base64.b64decode(content) if isinstance(content, str) else bytes(content)
            self.env["flousflow.whatsapp.media.policy"].validate(
                filename, mimetype, len(raw), raw[:65536], conversation.number_id.attachment_limit_mb
            )
            attachment = self.env["ir.attachment"].sudo().create(
                {
                    "name": filename or "WhatsApp attachment",
                    "datas": base64.b64encode(raw),
                    "mimetype": mimetype,
                    "res_model": self._name,
                }
            )
        message = self.sudo().create(
            {
                "conversation_id": conversation.id,
                "direction": "outbound",
                "source": "odoo",
                "message_type": payload.get("message_type", "text"),
                "body": payload.get("body"),
                "attachment_id": attachment.id if attachment else False,
                "voice_note": bool(payload.get("voice_note")) and payload.get("message_type") == "audio",
                "service_window_override": override,
                "service_window_override_reason": override_reason or False,
                "client_idempotency_key": key,
                "author_user_id": self.env.user.id,
                "state": "queued",
                "next_attempt_at": fields.Datetime.now(),
            }
        )
        if attachment:
            attachment.write({"res_id": message.id})
        if override:
            self.env["flousflow.whatsapp.audit.event"].sudo().create({
                "company_id": conversation.company_id.id,
                "event_type": "service_window_override",
                "actor_user_id": self.env.user.id,
                "conversation_id": conversation.id,
                "number_id": number.id,
                "reason": override_reason,
                "correlation_id": key,
                "metadata_json": {"message_id": message.id, "window_hours": number.service_window_hours},
            })
        conversation._notify_realtime("message", message)
        return message

    @api.model
    def claim_outbox(self, number, limit=20):
        now = fields.Datetime.now()
        self.flush_model(["number_id", "direction", "state", "next_attempt_at", "create_date"])
        self.env.cr.execute(
            "SELECT id FROM flousflow_whatsapp_message "
            "WHERE direction = 'outbound' AND number_id = %s "
            "AND ("
            "    (state = 'queued' AND (next_attempt_at IS NULL OR next_attempt_at <= %s)) "
            " OR (state = 'failed' AND next_attempt_at IS NOT NULL AND next_attempt_at <= %s)"
            ") "
            "ORDER BY create_date, id FOR UPDATE SKIP LOCKED LIMIT %s",
            [number.id, now, now, max(1, min(int(limit or 20), 100))],
        )
        messages = self.sudo().browse([row[0] for row in self.env.cr.fetchall()])
        for message in messages:
            message.write({"state": "sending", "attempt_count": message.attempt_count + 1})
        return messages

    def mark_sent(self, external_message_id=None, sent_at=None):
        sent_at = sent_at or fields.Datetime.now()
        for message in self:
            values = {"next_attempt_at": False, "error_code": False, "error_summary": False}
            if message.state not in {"sent", "delivered", "read"}:
                values.update({"state": "sent", "sent_at": sent_at})
            elif not message.sent_at:
                values["sent_at"] = sent_at
            if external_message_id:
                echoed = self.sudo().search([
                    ("id", "!=", message.id),
                    ("number_id", "=", message.number_id.id),
                    ("external_message_id", "=", external_message_id),
                    ("source", "=", "whatsapp_device"),
                ], limit=1)
                if echoed:
                    echoed.unlink()
                values["external_message_id"] = external_message_id
            message.write(values)
            message.conversation_id.sudo()._register_outbound_response(message)
            message.conversation_id.sudo()._notify_realtime("message", message)
        return True

    def mark_delivered(self, delivered_at=None):
        for message in self:
            values = {}
            if message.state != "read":
                values["state"] = "delivered"
            if not message.delivered_at:
                values["delivered_at"] = delivered_at or fields.Datetime.now()
            if values:
                message.write(values)
            message.conversation_id.sudo()._notify_realtime("message", message)
        return True

    def mark_read(self, read_at=None):
        for message in self:
            now = read_at or fields.Datetime.now()
            values = {"state": "read"}
            if not message.delivered_at:
                values["delivered_at"] = now
            if not message.read_at:
                values["read_at"] = now
            message.write(values)
            message.conversation_id.sudo()._notify_realtime("message", message)
        return True

    def mark_failed(self, code, summary, retry_at=None, permanent=False):
        if retry_at and not permanent:
            try:
                retry_at = fields.Datetime.to_datetime(retry_at)
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("The outbound retry timestamp is invalid.")) from exc
        self.write(
            {
                "state": "failed",
                "error_code": (code or "")[:128],
                "error_summary": (summary or "")[:1000],
                "next_attempt_at": False if permanent else retry_at,
            }
        )
        for message in self:
            message.conversation_id.sudo()._notify_realtime("message", message)
        return True

    def action_retry_failed(self):
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_supervisor"):
            raise AccessError(_("Only a WhatsApp supervisor can retry failed messages."))
        invalid = self.filtered(lambda message: message.direction != "outbound" or message.state != "failed")
        if invalid:
            raise ValidationError(_("Only failed outbound messages can be retried."))
        now = fields.Datetime.now()
        for message in self:
            message.sudo().write({
                "state": "queued", "attempt_count": 0, "next_attempt_at": now,
                "error_code": False, "error_summary": False,
            })
            self.env["flousflow.whatsapp.audit.event"].sudo().create({
                "company_id": message.company_id.id,
                "event_type": "manual_retry",
                "actor_user_id": self.env.user.id,
                "conversation_id": message.conversation_id.id,
                "number_id": message.number_id.id,
                "correlation_id": message.client_idempotency_key,
                "metadata_json": {"message_id": message.id},
            })
            message.conversation_id.sudo()._notify_realtime("message", message)
        return True

    @api.model
    def cron_fail_stale_outbound(self, now=None):
        """Fail outbound messages that never left the outbox.

        If the external connector service is down, messages stay ``queued`` /
        ``sending`` forever. This cron fails them after a configurable timeout
        and schedules a retry so they are not silently lost.
        """
        now = now or fields.Datetime.now()
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "flousflow_whatsapp.outbound_stale_minutes", "15"
        )
        try:
            minutes = max(1, int(raw))
        except (TypeError, ValueError):
            minutes = 15
        cutoff = now - timedelta(minutes=minutes)
        stale = self.sudo().search(
            [
                ("direction", "=", "outbound"),
                ("state", "in", ["queued", "sending"]),
                ("create_date", "<", cutoff),
            ],
            limit=200,
        )
        for message in stale:
            message.mark_failed(
                "stale_outbound",
                _("Not delivered to the connector within %s minutes.", minutes),
                retry_at=now + timedelta(minutes=5),
            )
        return len(stale)

    def unlink(self):
        if not self.env.su:
            raise AccessError(_("WhatsApp message history cannot be deleted."))
        return super().unlink()
