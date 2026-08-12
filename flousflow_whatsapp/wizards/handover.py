from odoo import fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappHandoverWizard(models.TransientModel):
    _name = "flousflow.whatsapp.handover.wizard"
    _description = "Hand Over Employee WhatsApp Conversations"

    employee_id = fields.Many2one("hr.employee", required=True)
    target_user_id = fields.Many2one("res.users", required=True, domain="[('share', '=', False)]")
    reason = fields.Text(required=True)

    def action_handover(self):
        self.ensure_one()
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_supervisor"):
            raise AccessError(_("Only a WhatsApp supervisor can hand over employee conversations."))
        if not self.employee_id.user_id:
            raise ValidationError(_("The employee is not linked to an Odoo user."))
        conversations = self.env["flousflow.whatsapp.conversation"].search([
            ("assigned_user_id", "=", self.employee_id.user_id.id),
            ("state", "in", ["open", "waiting_internal", "escalated"]),
        ])
        for conversation in conversations:
            wizard = self.env["flousflow.whatsapp.transfer.wizard"].create({
                "conversation_id": conversation.id, "target_user_id": self.target_user_id.id,
                "reason": self.reason,
            })
            wizard.action_transfer()
        return {"type": "ir.actions.act_window_close"}
