from odoo import fields, models, _
from odoo.exceptions import AccessError


class FlousflowWhatsappAuditEvent(models.Model):
    _name = "flousflow.whatsapp.audit.event"
    _description = "Flous Flow WhatsApp Audit Event"
    _order = "occurred_at desc, id desc"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, index=True, ondelete="cascade")
    event_type = fields.Char(required=True, index=True)
    actor_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    conversation_id = fields.Many2one(
        "flousflow.whatsapp.conversation",
        ondelete="set null",
        index=True,
    )
    number_id = fields.Many2one(
        "flousflow.whatsapp.number",
        ondelete="set null",
        index=True,
    )
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    reason = fields.Text()
    correlation_id = fields.Char(index=True)
    metadata_json = fields.Json(default=dict)

    def write(self, values):
        if not self.env.su:
            raise AccessError(_("WhatsApp audit events are immutable."))
        return super().write(values)

    def unlink(self):
        if not self.env.su:
            raise AccessError(_("WhatsApp audit events cannot be deleted."))
        return super().unlink()
