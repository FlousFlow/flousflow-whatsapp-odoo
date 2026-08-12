from odoo import api, models


class MailPresence(models.Model):
    _inherit = "mail.presence"

    @api.model_create_multi
    def create(self, vals_list):
        presences = super().create(vals_list)
        Interval = self.env["flousflow.whatsapp.presence.interval"]
        for presence in presences.filtered("user_id"):
            Interval.record_transition(
                presence.user_id,
                presence.user_id.im_status or "offline",
                source="presence",
            )
        return presences

    def write(self, values):
        users = self.user_id
        result = super().write(values)
        if {"status", "last_poll", "last_presence"}.intersection(values):
            Interval = self.env["flousflow.whatsapp.presence.interval"]
            for user in users:
                Interval.record_transition(
                    user,
                    user.im_status or "offline",
                    source="presence",
                )
        return result
