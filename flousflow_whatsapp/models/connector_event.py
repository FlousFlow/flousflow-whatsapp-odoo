import base64
import binascii
import re
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import BinaryBytes


class FlousflowWhatsappConnectorEvent(models.Model):
    _name = "flousflow.whatsapp.connector.event"
    _description = "Flous Flow WhatsApp Connector Event"
    _order = "received_at desc, id desc"

    number_id = fields.Many2one("flousflow.whatsapp.number", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="number_id.company_id", store=True, index=True)
    external_event_id = fields.Char(required=True, index=True)
    event_type = fields.Char(required=True)
    received_at = fields.Datetime(required=True, default=fields.Datetime.now)
    processed_at = fields.Datetime(copy=False)
    message_id = fields.Many2one("flousflow.whatsapp.message", ondelete="set null")
    payload_digest = fields.Char()

    _event_unique = models.Constraint(
        "UNIQUE(number_id, external_event_id)", "This connector event was already received."
    )

    @api.model
    def ingest_inbound(self, payload):
        source_jid = (payload.get("source_jid") or "").strip().lower()
        if source_jid.endswith(("@broadcast", "@newsletter", "@g.us")):
            raise ValidationError(_("WhatsApp status stories are not customer messages."))
        number = self.env["flousflow.whatsapp.number"].sudo().browse(payload.get("number_id")).exists()
        external_id = payload.get("external_message_id")
        if not number or not external_id:
            raise ValidationError(_("A valid number and external message ID are required."))
        if not number.allow_inbound:
            raise ValidationError(_("Inbound synchronization is disabled for this WhatsApp number."))
        existing_message = self.env["flousflow.whatsapp.message"].sudo().search(
            [("number_id", "=", number.id), ("external_message_id", "=", external_id)], limit=1
        )
        if existing_message:
            return existing_message
        event = self.sudo().search(
            [("number_id", "=", number.id), ("external_event_id", "=", external_id)], limit=1
        )
        if event and event.message_id:
            return event.message_id
        phone = payload.get("customer_phone_normalized")
        if not isinstance(phone, str) or not re.fullmatch(r"\+?\d{7,15}", phone):
            raise ValidationError(_("A valid customer phone number is required."))
        direction = payload.get("direction") or "inbound"
        if direction not in {"inbound", "outbound"}:
            raise ValidationError(_("The WhatsApp message direction is invalid."))
        event = event or self.sudo().create(
            {"number_id": number.id, "external_event_id": external_id, "event_type": "message"}
        )
        conversation = self.env["flousflow.whatsapp.conversation"].sudo().search(
            [("number_id", "=", number.id), ("customer_phone_normalized", "=", phone),
             ("state", "not in", ["closed", "spam", "blocked"])], limit=1
        )
        now = fields.Datetime.now()
        if not conversation:
            partner = self.env["res.partner"].sudo()._find_whatsapp_partner(
                phone, number.company_id
            )
            conversation = self.env["flousflow.whatsapp.conversation"].sudo().create(
                {"number_id": number.id, "team_id": number.primary_team_id.id,
                 "company_id": number.company_id.id, "customer_phone_normalized": phone,
                 "customer_display_name": payload.get("customer_name") or False,
                 "partner_id": partner.id, "state": "unassigned"}
            )
        self.env.cr.execute(
            "SELECT id FROM flousflow_whatsapp_conversation WHERE id = %s FOR UPDATE",
            [conversation.id],
        )
        conversation.invalidate_recordset(["assigned_user_id", "state", "lock_ids"])
        partner = conversation.partner_id
        if partner and payload.get("customer_name"):
            current_digits = re.sub(r"\D", "", partner.name or "")
            phone_digits = re.sub(r"\D", "", phone)
            if current_digits and current_digits == phone_digits:
                partner.write({"name": payload["customer_name"][:255]})
        if payload.get("customer_name") and conversation.customer_display_name != payload.get("customer_name"):
            conversation.customer_display_name = payload["customer_name"][:255]
        is_video = payload.get("message_type") == "video" or (payload.get("mimetype") or "").startswith("video/")
        attachment = False
        encoded_content = payload.get("content_base64")
        if encoded_content and not is_video:
            try:
                raw = base64.b64decode(encoded_content, validate=True)
            except (binascii.Error, TypeError, ValueError) as exc:
                raise ValidationError(_("Inbound attachment content is not valid base64.")) from exc
            self.env["flousflow.whatsapp.media.policy"].validate(
                payload.get("filename"), payload.get("mimetype"), len(raw), raw[:65536],
                number.attachment_limit_mb,
            )
            attachment = self.env["ir.attachment"].sudo().create({
                "name": payload.get("filename") or "WhatsApp attachment",
                "raw": BinaryBytes(raw, filename=payload.get("filename") or "WhatsApp attachment"),
                "mimetype": payload.get("mimetype") or "application/octet-stream",
                "res_model": "flousflow.whatsapp.message",
            })
        def _parse_datetime(value):
            """Parse an ISO-8601 / SQL string into a naive UTC datetime."""
            if not value:
                return False
            if isinstance(value, datetime):
                parsed = value
                return (
                    parsed.astimezone(timezone.utc).replace(tzinfo=None)
                    if parsed.tzinfo
                    else parsed
                )
            text = str(value).strip()
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return (
                    parsed.astimezone(timezone.utc).replace(tzinfo=None)
                    if parsed.tzinfo
                    else parsed
                )
            except ValueError:
                try:
                    return fields.Datetime.to_datetime(text)
                except (TypeError, ValueError):
                    return False

        message = self.env["flousflow.whatsapp.message"].sudo().create(
            {"conversation_id": conversation.id, "direction": direction,
             "source": "customer" if direction == "inbound" else "whatsapp_device",
             "message_type": "video_metadata" if is_video else payload.get("message_type", "text"),
             "body": payload.get("body") or ("Incoming video was blocked by media policy." if is_video else False),
             "attachment_id": attachment.id if attachment else False,
             "voice_note": bool(payload.get("voice_note")) and payload.get("message_type") == "audio",
             "external_message_id": external_id,
             "state": "received" if direction == "inbound" else "sent",
             "sent_at": _parse_datetime(payload.get("sent_at")) or (fields.Datetime.now() if direction == "outbound" else False)}
        )
        if attachment:
            attachment.write({"res_id": message.id})
        if direction == "inbound":
            is_backfill = bool(payload.get("backfill"))
            first = not conversation.first_customer_message_at
            if is_backfill:
                # History backfill: record the conversation/message without
                # touching SLA, assignment or the unread badge (those apply to
                # live, actionable messages only).
                message_at = _parse_datetime(payload.get("sent_at")) or now
                values = {"last_message_at": message_at}
                if not conversation.last_customer_message_at or message_at > conversation.last_customer_message_at:
                    values["last_customer_message_at"] = message_at
                conversation.write(values)
                conversation._notify_realtime("message", message)
                event.write({"message_id": message.id, "processed_at": now})
                return message
            values = {"last_message_at": now, "last_customer_message_at": now, "waiting_since": now, "state": "open" if conversation.assigned_user_id else "unassigned"}
            if first:
                values.update({"first_customer_message_at": now,
                               "response_due_at": now + timedelta(minutes=number.first_response_minutes),
                               "sla_state": "ok"})
            elif conversation.first_response_at:
                values["response_due_at"] = now + timedelta(minutes=number.reply_response_minutes)
                values["sla_state"] = "ok"
            conversation.write(values)
            conversation.assign_available_agent()
            # Only count as unread when no agent is actively viewing the
            # conversation (an active, non-expired write lock means the inbox
            # has it open). The frontend clears the badge via mark_seen().
            active_lock = conversation.lock_ids.filtered(
                lambda lock: not lock.released_at and lock.expires_at > now
            )
            if not active_lock:
                conversation.write({"unread_count": conversation.unread_count + 1})
        else:
            conversation._register_outbound_response(message)
            conversation._release_lock_for_external_reply(message)
        event.write({"message_id": message.id, "processed_at": now})
        conversation._notify_realtime("message", message)
        return message
