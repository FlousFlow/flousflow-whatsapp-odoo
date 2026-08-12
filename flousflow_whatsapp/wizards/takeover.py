from odoo import fields, models, _
from odoo.exceptions import AccessError


class FlousflowWhatsappTakeoverWizard(models.TransientModel):
    _name = "flousflow.whatsapp.takeover.wizard"
    _description = "Take Over WhatsApp Conversation"

    conversation_id = fields.Many2one("flousflow.whatsapp.conversation", required=True)
    reason = fields.Text(required=True)

    def action_takeover(self):
        self.ensure_one()
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_supervisor"):
            raise AccessError(_("Only a WhatsApp supervisor can take over a conversation."))
        conversation = self.conversation_id
        old_lock = conversation._active_write_lock()
        if old_lock:
            old_lock.sudo().write({
                "released_at": fields.Datetime.now(), "release_reason": "takeover",
                "takeover_by_id": self.env.user.id, "takeover_reason": self.reason,
            })
            old_lock.flush_recordset(["released_at"])
        previous_user = conversation.assigned_user_id
        conversation.sudo().write({
            "assigned_user_id": self.env.user.id, "assigned_at": fields.Datetime.now(),
            "assignment_release_at": False, "state": "open",
        })
        self.env["flousflow.whatsapp.audit.event"].sudo().create({
            "company_id": conversation.company_id.id, "event_type": "supervisor_takeover",
            "actor_user_id": self.env.user.id, "conversation_id": conversation.id,
            "number_id": conversation.number_id.id, "reason": self.reason,
            "metadata_json": {"previous_user_id": previous_user.id},
        })
        conversation.acquire_write_lock()
        return {"type": "ir.actions.act_window_close"}
