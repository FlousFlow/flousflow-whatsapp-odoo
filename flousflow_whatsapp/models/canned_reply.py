from odoo import fields, models


class FlousflowWhatsappCannedReply(models.Model):
    _name = "flousflow.whatsapp.canned.reply"
    _description = "Flous Flow WhatsApp Canned Reply"
    _order = "name, id"

    name = fields.Char(required=True)
    body = fields.Text(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, ondelete="cascade")
    team_id = fields.Many2one("flousflow.whatsapp.team", ondelete="cascade", check_company=True)
    number_id = fields.Many2one("flousflow.whatsapp.number", ondelete="cascade", check_company=True)
    active = fields.Boolean(default=True)
