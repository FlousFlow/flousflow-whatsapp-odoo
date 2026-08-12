from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    whatsapp_presence_interval_count = fields.Integer(
        compute="_compute_whatsapp_presence_metrics"
    )
    whatsapp_online_seconds = fields.Integer(
        string="Recorded WhatsApp Online Seconds",
        compute="_compute_whatsapp_presence_metrics",
    )
    whatsapp_conversation_count = fields.Integer(compute="_compute_whatsapp_conversation_count")

    @api.depends("user_id")
    def _compute_whatsapp_presence_metrics(self):
        Interval = self.env["flousflow.whatsapp.presence.interval"]
        grouped = Interval._read_group(
            [("employee_id", "in", self.ids)],
            ["employee_id"],
            ["__count", "online_seconds:sum"],
        )
        values = {
            employee.id: (count, online_seconds or 0)
            for employee, count, online_seconds in grouped
        }
        for employee in self:
            count, online_seconds = values.get(employee.id, (0, 0))
            employee.whatsapp_presence_interval_count = count
            employee.whatsapp_online_seconds = online_seconds

    def action_open_whatsapp_presence_intervals(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp Availability",
            "res_model": "flousflow.whatsapp.presence.interval",
            "view_mode": "list,pivot,graph",
            "domain": [("employee_id", "=", self.id)],
            "context": {"create": False, "edit": False, "delete": False},
        }

    @api.depends("user_id")
    def _compute_whatsapp_conversation_count(self):
        grouped = self.env["flousflow.whatsapp.conversation"]._read_group(
            [("assigned_user_id", "in", self.user_id.ids)], ["assigned_user_id"], ["__count"]
        )
        counts = {user.id: count for user, count in grouped}
        for employee in self:
            employee.whatsapp_conversation_count = counts.get(employee.user_id.id, 0)

    def action_open_whatsapp_conversations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "WhatsApp Conversations",
            "res_model": "flousflow.whatsapp.conversation", "view_mode": "list,form",
            "domain": [("assigned_user_id", "=", self.user_id.id)],
        }

    def action_open_whatsapp_handover_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Hand Over WhatsApp Conversations",
            "res_model": "flousflow.whatsapp.handover.wizard", "view_mode": "form",
            "target": "new", "context": {"default_employee_id": self.id},
        }
