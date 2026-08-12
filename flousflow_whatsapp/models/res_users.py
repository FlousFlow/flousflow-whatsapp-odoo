from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    def write(self, values):
        track_manual_presence = "manual_im_status" in values
        result = super().write(values)
        if track_manual_presence and "flousflow.whatsapp.presence.interval" in self.env:
            # Odoo's profile dropdown stores False for the explicit Online
            # choice. If the last mail.presence row is still offline, merely
            # clearing the manual override keeps the effective im_status
            # offline until the next bus poll. Refresh the standard Odoo
            # presence immediately so routing and availability agree with the
            # status the user just selected.
            if not values.get("manual_im_status"):
                Presence = self.env["mail.presence"]
                for user in self:
                    Presence._update_presence(user, inactivity_period=0)
                self.invalidate_recordset(["im_status"])
                self.partner_id.invalidate_recordset(["im_status"])
            Interval = self.env["flousflow.whatsapp.presence.interval"]
            for user in self:
                Interval.record_transition(
                    user,
                    user.im_status or "offline",
                    source="manual",
                )
        return result
