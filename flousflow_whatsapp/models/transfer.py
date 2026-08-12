from odoo import fields, models


class FlousflowWhatsappTransfer(models.Model):
    _name = "flousflow.whatsapp.transfer"
    _description = "Flous Flow WhatsApp Transfer"
    _order = "requested_at desc, id desc"

    conversation_id = fields.Many2one("flousflow.whatsapp.conversation", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="conversation_id.company_id", store=True, index=True)
    source_user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    target_user_id = fields.Many2one("res.users", ondelete="restrict")
    target_team_id = fields.Many2one("flousflow.whatsapp.team", ondelete="restrict")
    reason = fields.Text(required=True)
    state = fields.Selection([("pending", "Pending"), ("accepted", "Accepted"), ("cancelled", "Cancelled")], default="pending", required=True)
    requested_at = fields.Datetime(default=fields.Datetime.now, required=True)
    accepted_at = fields.Datetime()
