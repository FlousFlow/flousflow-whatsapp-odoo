from odoo import fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappTransferWizard(models.TransientModel):
    _name = "flousflow.whatsapp.transfer.wizard"
    _description = "Transfer WhatsApp Conversation"

    conversation_id = fields.Many2one("flousflow.whatsapp.conversation", required=True)
    target_user_id = fields.Many2one("res.users", domain="[('share', '=', False)]")
    target_team_id = fields.Many2one("flousflow.whatsapp.team")
    reason = fields.Text(required=True)

    def action_transfer(self):
        self.ensure_one()
        conversation = self.conversation_id
        is_supervisor = self.env.user.has_group("flousflow_whatsapp.group_whatsapp_supervisor")
        if conversation.assigned_user_id != self.env.user and not is_supervisor:
            raise AccessError(_("Only the assignee or a supervisor can transfer this conversation."))
        if bool(self.target_user_id) == bool(self.target_team_id):
            raise ValidationError(_("Choose either one target user or one target team."))
        if self.target_user_id and not conversation.number_id.user_can_access(self.target_user_id):
            raise ValidationError(_("The target user cannot access this WhatsApp number."))
        conversation.release_write_lock("transfer")
        self.env["flousflow.whatsapp.transfer"].sudo().create({
            "conversation_id": conversation.id,
            "source_user_id": conversation.assigned_user_id.id or self.env.user.id,
            "target_user_id": self.target_user_id.id,
            "target_team_id": self.target_team_id.id,
            "reason": self.reason,
            "state": "accepted", "accepted_at": fields.Datetime.now(),
        })
        values = {"assignment_release_at": False}
        if self.target_user_id:
            values.update({"assigned_user_id": self.target_user_id.id, "team_id": conversation.team_id.id,
                           "assigned_at": fields.Datetime.now(), "state": "open"})
        else:
            values.update({"assigned_user_id": False, "assigned_at": False,
                           "team_id": self.target_team_id.id, "state": "unassigned"})
        conversation.sudo().write(values)
        if self.target_team_id:
            conversation.sudo().assign_available_agent()
        return {"type": "ir.actions.act_window_close"}
