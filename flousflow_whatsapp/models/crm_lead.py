from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    whatsapp_conversation_count = fields.Integer(compute="_compute_whatsapp_conversation_count")

    def _compute_whatsapp_conversation_count(self):
        grouped = self.env["flousflow.whatsapp.conversation"]._read_group(
            [("lead_id", "in", self.ids)], ["lead_id"], ["__count"]
        )
        counts = {lead.id: count for lead, count in grouped}
        for lead in self:
            lead.whatsapp_conversation_count = counts.get(lead.id, 0)

    def action_open_whatsapp_conversations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "WhatsApp Conversations",
            "res_model": "flousflow.whatsapp.conversation", "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {"default_lead_id": self.id, "default_partner_id": self.partner_id.id},
        }
