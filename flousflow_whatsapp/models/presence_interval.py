from odoo import api, fields, models


PRESENCE_STATUSES = {"online", "away", "busy", "offline"}


class FlousflowWhatsappPresenceInterval(models.Model):
    _name = "flousflow.whatsapp.presence.interval"
    _description = "Flous Flow WhatsApp Presence Interval"
    _order = "started_at desc, id desc"
    _check_company_auto = True

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one("hr.employee", ondelete="set null", index=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="cascade", index=True)
    status = fields.Selection(
        [("online", "Online"), ("away", "Away"), ("busy", "Do Not Disturb"), ("offline", "Offline")],
        required=True,
        index=True,
    )
    started_at = fields.Datetime(required=True, index=True)
    ended_at = fields.Datetime(index=True)
    duration_seconds = fields.Integer(compute="_compute_duration", store=True)
    online_seconds = fields.Integer(compute="_compute_duration", store=True)
    source = fields.Selection(
        [("presence", "Odoo Presence"), ("manual", "Manual Profile Status"), ("reconcile", "Reconciliation")],
        required=True,
        default="presence",
    )

    _one_open_interval_per_user = models.UniqueIndex(
        "(user_id) WHERE ended_at IS NULL"
    )

    @api.depends("started_at", "ended_at", "status")
    def _compute_duration(self):
        now = fields.Datetime.now()
        for interval in self:
            end = interval.ended_at or now
            seconds = max(0, int((end - interval.started_at).total_seconds()))
            interval.duration_seconds = seconds
            interval.online_seconds = seconds if interval.status == "online" else 0

    @api.model
    def record_transition(self, user, effective_status, occurred_at=None, source="presence"):
        if not user or effective_status not in PRESENCE_STATUSES:
            return self.browse()
        occurred_at = occurred_at or fields.Datetime.now()
        # Serialize transitions per user before checking the partial unique index.
        # Locking only an existing open interval is insufficient when two workers
        # concurrently create the first interval for the same user.
        self.env.cr.execute(
            "SELECT id FROM res_users WHERE id = %s FOR UPDATE",
            [user.id],
        )
        self.flush_model(["user_id", "status", "started_at", "ended_at"])
        self.env.cr.execute(
            "SELECT id FROM flousflow_whatsapp_presence_interval "
            "WHERE user_id = %s AND ended_at IS NULL FOR UPDATE",
            [user.id],
        )
        row = self.env.cr.fetchone()
        current = self.sudo().browse(row[0]) if row else self.browse()
        if current and current.status == effective_status:
            return current
        if current:
            end = max(occurred_at, current.started_at)
            current.sudo().write({"ended_at": end})
            current.flush_recordset(["ended_at"])
        employee = user.employee_id
        return self.sudo().create(
            {
                "user_id": user.id,
                "employee_id": employee.id if employee else False,
                "company_id": (employee.company_id or user.company_id).id,
                "status": effective_status,
                "started_at": occurred_at,
                "source": source,
            }
        )

    @api.model
    def cron_reconcile_presence(self):
        group = self.env.ref("flousflow_whatsapp.group_whatsapp_agent", raise_if_not_found=False)
        if not group:
            return True
        now = fields.Datetime.now()
        users = group.all_user_ids.filtered(lambda user: user.active and not user.share)
        for user in users:
            self.record_transition(user, user.im_status or "offline", now, source="reconcile")
        open_intervals = self.sudo().search([("ended_at", "=", False)])
        inactive_intervals = open_intervals.filtered(lambda interval: not interval.user_id.active)
        inactive_intervals.write({"ended_at": now})
        Conversation = self.env["flousflow.whatsapp.conversation"].sudo()
        Conversation.update_non_online_grace(now=now)
        Conversation.process_non_online_grace(now=now)
        return True
