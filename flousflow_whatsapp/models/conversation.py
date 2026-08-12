from collections import defaultdict
from datetime import timedelta
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


OPEN_WORKLOAD_STATES = ("open", "waiting_internal", "escalated")


class FlousflowWhatsappConversation(models.Model):
    _name = "flousflow.whatsapp.conversation"
    _description = "Flous Flow WhatsApp Conversation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "last_message_at desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default="/", copy=False, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
    )
    number_id = fields.Many2one(
        "flousflow.whatsapp.number",
        required=True,
        check_company=True,
        index=True,
        ondelete="restrict",
    )
    team_id = fields.Many2one(
        "flousflow.whatsapp.team",
        required=True,
        check_company=True,
        index=True,
        ondelete="restrict",
    )
    partner_id = fields.Many2one("res.partner", check_company=True, ondelete="set null", index=True)
    lead_id = fields.Many2one("crm.lead", check_company=True, ondelete="set null", index=True)
    assigned_user_id = fields.Many2one(
        "res.users",
        check_company=True,
        ondelete="set null",
        index=True,
        tracking=True,
    )
    assigned_at = fields.Datetime(copy=False, readonly=True)
    state = fields.Selection(
        [
            ("new", "New"),
            ("unassigned", "Unassigned"),
            ("open", "Open"),
            ("waiting_customer", "Waiting for Customer"),
            ("waiting_internal", "Waiting for Internal Action"),
            ("escalated", "Escalated"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
            ("spam", "Spam"),
            ("blocked", "Blocked"),
        ],
        required=True,
        default="new",
        tracking=True,
        index=True,
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Important"), ("2", "Urgent")],
        required=True,
        default="0",
        index=True,
    )
    customer_phone_normalized = fields.Char(required=True, index=True)
    customer_display_name = fields.Char(
        string="WhatsApp Display Name",
        help="Profile name reported by WhatsApp. This does not create a contact.",
    )
    first_customer_message_at = fields.Datetime(copy=False)
    last_customer_message_at = fields.Datetime(copy=False, index=True)
    waiting_since = fields.Datetime(copy=False)
    first_response_at = fields.Datetime(copy=False)
    response_due_at = fields.Datetime(copy=False, index=True)
    assignment_release_at = fields.Datetime(copy=False, index=True)
    last_message_at = fields.Datetime(default=fields.Datetime.now, index=True)
    sla_state = fields.Selection(
        [("ok", "On Time"), ("warning", "Warning"), ("breached", "Breached"), ("paused", "Paused")],
        required=True,
        default="ok",
        index=True,
    )
    lock_ids = fields.One2many(
        "flousflow.whatsapp.conversation.lock",
        "conversation_id",
        string="Write Locks",
    )
    whatsapp_message_ids = fields.One2many(
        "flousflow.whatsapp.message", "conversation_id", string="WhatsApp Messages"
    )
    unread_count = fields.Integer(
        string="Unread Messages",
        default=0,
        copy=False,
        help="Number of inbound WhatsApp messages not yet opened by an agent.",
    )
    customer_typing = fields.Boolean(
        string="Customer Typing",
        default=False,
        copy=False,
        help="Whether the customer is currently typing (reported by the connector).",
    )
    last_typing_at = fields.Datetime(copy=False)

    def _realtime_users(self):
        self.ensure_one()
        teams = self.number_id.primary_team_id | self.number_id.allowed_team_ids
        users = (
            teams.member_ids
            | teams.supervisor_ids
            | self.number_id.allowed_user_ids
            | self.number_id.manager_user_id
        ) - self.number_id.denied_user_ids
        admin_group = self.env.ref("flousflow_whatsapp.group_whatsapp_admin")
        users |= admin_group.user_ids.filtered(
            lambda user: self.company_id in user.company_ids
        )
        return users.filtered(lambda user: user.active and not user.share)

    def _notify_realtime(self, event_type, message=False, **extra):
        for conversation in self:
            payload = {
                "conversation_id": conversation.id,
                "message_id": message.id if message else False,
                "event": event_type,
                "direction": message.direction if message else False,
                "source": message.source if message else False,
            }
            payload.update(extra)
            for partner in conversation._realtime_users().mapped("partner_id"):
                partner._bus_send("flousflow_whatsapp.message", payload)
        return True

    def mark_seen(self):
        """Clear the unread badge when an agent opens the conversation."""
        unread = self.filtered(lambda conversation: conversation.unread_count)
        if unread:
            unread.sudo().write({"unread_count": 0})
            for conversation in unread:
                conversation._notify_realtime("seen")
        return True

    def set_customer_typing(self, typing):
        """Update the customer-typing indicator reported by the connector."""
        now = fields.Datetime.now()
        for conversation in self:
            typing = bool(typing)
            values = {"last_typing_at": now}
            if conversation.customer_typing != typing:
                values["customer_typing"] = typing
            conversation.write(values)
            conversation._notify_realtime("typing", typing=typing)
        return True

    def action_close_from_inbox(self):
        """Close / resolve the conversation directly from the shared inbox."""
        self.ensure_one()
        if not self.number_id.user_can_access(self.env.user):
            raise AccessError(_("You are not allowed to use this WhatsApp number."))
        is_manager = self.env.user.has_group(
            "flousflow_whatsapp.group_whatsapp_supervisor"
        )
        if (
            self.assigned_user_id
            and self.assigned_user_id != self.env.user
            and not is_manager
        ):
            raise AccessError(
                _("Only the assigned agent or a supervisor can close this conversation.")
            )
        active_locks = self.lock_ids.filtered(lambda lock: not lock.released_at)
        active_locks.sudo().write(
            {
                "released_at": fields.Datetime.now(),
                "release_reason": "close",
            }
        )
        self.write(
            {
                "state": "closed",
                "waiting_since": False,
                "response_due_at": False,
                "assignment_release_at": False,
                "unread_count": 0,
            }
        )
        self._notify_realtime("closed")
        return True

    @api.model
    def refresh_display_names(self):
        """Backfill display names from matching res.partner records.

        Called after a history sync so conversations created from WhatsApp
        history get the saved contact name when the phone matches an existing
        partner (the profile name from WhatsApp is applied per-message by the
        connector; this covers the saved-name case).
        """
        conversations = self.search([("partner_id", "!=", False)])
        for conversation in conversations:
            partner = conversation.partner_id
            if not partner.name:
                continue
            current_digits = re.sub(r"\D", "", conversation.customer_display_name or "")
            phone_digits = re.sub(r"\D", "", conversation.customer_phone_normalized or "")
            if current_digits and current_digits == phone_digits:
                conversation.sudo().write({"customer_display_name": partner.name[:255]})
        return True

    def action_open_lead_wizard(self):
        self.ensure_one()
        self._link_existing_whatsapp_lead()
        if self.lead_id:
            return {
                "type": "ir.actions.act_window",
                "name": _("CRM Lead"),
                "res_model": "crm.lead",
                "res_id": self.lead_id.id,
                "view_mode": "form",
            }
        if self.assigned_user_id != self.env.user:
            raise AccessError(
                _("Assign this conversation to yourself before creating a CRM lead.")
            )
        view = self.env.ref(
            "flousflow_whatsapp.view_whatsapp_lead_wizard_form"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Create CRM Lead"),
            "res_model": "flousflow.whatsapp.lead.wizard",
            "view_mode": "form",
            "view_id": view.id,
            "views": [(view.id, "form")],
            "target": "new",
            "context": {"default_conversation_id": self.id},
        }

    def _lock_whatsapp_lead_creation(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
            [self.company_id.id, self.customer_phone_normalized],
        )

    def _find_existing_whatsapp_lead(self):
        self.ensure_one()
        linked = self.sudo().search(
            [
                ("id", "!=", self.id),
                ("company_id", "=", self.company_id.id),
                ("customer_phone_normalized", "=", self.customer_phone_normalized),
                ("lead_id", "!=", False),
            ],
            order="id",
            limit=1,
        )
        return linked.lead_id

    def _link_existing_whatsapp_lead(self):
        self.ensure_one()
        if self.lead_id:
            return self.lead_id
        lead = self._find_existing_whatsapp_lead()
        if lead:
            values = {"lead_id": lead.id}
            if not self.partner_id and lead.partner_id:
                values["partner_id"] = lead.partner_id.id
            self.sudo().write(values)
        return lead

    def get_document_actions(self):
        self.ensure_one()
        if not self.number_id.user_can_access(self.env.user):
            raise AccessError(_("You are not allowed to use this WhatsApp number."))
        return self.env["flousflow.whatsapp.document.provider"].get_actions(self)

    def action_open_document_wizard(self, provider_key):
        self.ensure_one()
        if self.assigned_user_id != self.env.user:
            raise AccessError(_("Only the assigned agent can send documents in this conversation."))
        if not self.partner_id:
            raise ValidationError(
                _("Create the CRM lead and contact before sending customer documents.")
            )
        return self.env["flousflow.whatsapp.document.provider"].open_wizard(
            provider_key, self
        )

    def action_open_transfer_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Transfer Conversation",
            "res_model": "flousflow.whatsapp.transfer.wizard", "view_mode": "form",
            "target": "new", "context": {"default_conversation_id": self.id},
        }

    def action_open_takeover_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Take Over Conversation",
            "res_model": "flousflow.whatsapp.takeover.wizard", "view_mode": "form",
            "target": "new", "context": {"default_conversation_id": self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]
        for values in vals_list:
            if values.get("name", "/") == "/":
                values["name"] = sequence.next_by_code("flousflow.whatsapp.conversation") or "/"
            if values.get("number_id") and not values.get("team_id"):
                values["team_id"] = self.env["flousflow.whatsapp.number"].browse(
                    values["number_id"]
                ).primary_team_id.id
        conversations = super().create(vals_list)
        for conversation in conversations.filtered(lambda item: not item.lead_id):
            conversation._link_existing_whatsapp_lead()
        return conversations

    @api.constrains("company_id", "number_id", "team_id")
    def _check_company_relations(self):
        for conversation in self:
            if (
                conversation.number_id.company_id != conversation.company_id
                or conversation.team_id.company_id != conversation.company_id
            ):
                raise AccessError(_("Conversation, number, and team must belong to one company."))

    def _eligible_online_users(self):
        self.ensure_one()
        number = self.number_id
        teams = number.primary_team_id | number.allowed_team_ids
        users = teams.member_ids | number.allowed_user_ids
        users -= number.denied_user_ids
        return users.filtered(
            lambda user: user.active
            and not user.share
            and user.im_status == "online"
            and number.user_can_access(user)
            and user.has_group("flousflow_whatsapp.group_whatsapp_agent")
        )

    def assign_available_agent(self):
        for conversation in self:
            if conversation.assigned_user_id or conversation.state not in {"new", "unassigned"}:
                continue
            candidates = conversation._eligible_online_users()
            if not candidates:
                conversation.state = "unassigned"
                continue
            counts = defaultdict(int)
            grouped = self._read_group(
                [
                    ("assigned_user_id", "in", candidates.ids),
                    ("state", "in", list(OPEN_WORKLOAD_STATES)),
                ],
                ["assigned_user_id"],
                ["__count"],
            )
            for assigned_user, count in grouped:
                if assigned_user:
                    counts[assigned_user.id] = count
            minimum = min(counts[user.id] for user in candidates)
            tied = candidates.filtered(lambda user: counts[user.id] == minimum).sorted("id")
            last_user = conversation.number_id.last_assigned_user_id
            if last_user in tied:
                position = tied.ids.index(last_user.id)
                chosen = tied[(position + 1) % len(tied)]
            else:
                chosen = tied[0]
            now = fields.Datetime.now()
            conversation.write(
                {
                    "assigned_user_id": chosen.id,
                    "assigned_at": now,
                    "assignment_release_at": False,
                    "state": "open",
                }
            )
            conversation.number_id.sudo().last_assigned_user_id = chosen
        return True

    def _register_outbound_response(self, message):
        now = fields.Datetime.now()
        for conversation in self:
            values = {"last_message_at": now, "waiting_since": False, "response_due_at": False, "sla_state": "ok"}
            if not conversation.first_response_at:
                values["first_response_at"] = now
            conversation.write(values)
        return True

    @api.model
    def cron_update_sla(self, now=None):
        now = now or fields.Datetime.now()
        warning_at = now + timedelta(minutes=1)
        self.flush_model(["response_due_at", "first_response_at", "state", "sla_state"])
        self.env.cr.execute(
            """
            WITH candidates AS (
                SELECT id,
                       CASE
                           WHEN response_due_at <= %s THEN 'breached'
                           WHEN response_due_at <= %s THEN 'warning'
                           ELSE 'ok'
                       END AS target_state
                  FROM flousflow_whatsapp_conversation
                 WHERE response_due_at IS NOT NULL
                   AND first_response_at IS NULL
                   AND state NOT IN ('resolved', 'closed', 'spam', 'blocked')
                   AND sla_state IS DISTINCT FROM CASE
                           WHEN response_due_at <= %s THEN 'breached'
                           WHEN response_due_at <= %s THEN 'warning'
                           ELSE 'ok'
                       END
                 ORDER BY response_due_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1000
            )
            UPDATE flousflow_whatsapp_conversation AS conversation
               SET sla_state = candidates.target_state,
                   write_uid = %s,
                   write_date = %s
              FROM candidates
             WHERE conversation.id = candidates.id
            RETURNING conversation.id
            """,
            [now, warning_at, now, warning_at, self.env.uid, now],
        )
        updated_ids = [row[0] for row in self.env.cr.fetchall()]
        if updated_ids:
            self.invalidate_model(["sla_state", "write_uid", "write_date"])
        return len(updated_ids)

    @api.model
    def update_non_online_grace(self, now=None):
        """Set/release the offline grace deadline for open conversations.

        Batch by user: prefetch each assigned user's presence once and write
        the affected conversations in two bulk updates instead of one write per
        record. This cron runs every minute, so it must stay cheap at scale.
        """
        now = now or fields.Datetime.now()
        conversations = self.search(
            [
                ("assigned_user_id", "!=", False),
                ("state", "in", list(OPEN_WORKLOAD_STATES)),
            ]
        )
        if not conversations:
            return True
        # Prefetch the effective presence of every assigned user in one go.
        statuses = {
            user.id: user.im_status for user in conversations.assigned_user_id
        }
        to_clear = self.browse()
        to_deadline = self.browse()
        for conversation in conversations:
            status = statuses.get(conversation.assigned_user_id.id, "offline")
            if status == "online":
                if conversation.assignment_release_at:
                    to_clear |= conversation
            elif not conversation.assignment_release_at:
                to_deadline |= conversation
        if to_clear:
            to_clear.write({"assignment_release_at": False})
        if to_deadline:
            to_deadline.write(
                {"assignment_release_at": now + timedelta(minutes=2)}
            )
        return True

    @api.model
    def process_non_online_grace(self, now=None):
        now = now or fields.Datetime.now()
        due = self.search(
            [
                ("assigned_user_id", "!=", False),
                ("assignment_release_at", "!=", False),
                ("assignment_release_at", "<=", now),
                ("state", "in", list(OPEN_WORKLOAD_STATES)),
            ]
        )
        for conversation in due:
            if conversation.assigned_user_id.im_status == "online":
                conversation.assignment_release_at = False
                continue
            previous_user = conversation.assigned_user_id
            active_locks = conversation.lock_ids.filtered(lambda lock: not lock.released_at)
            active_locks.sudo().write(
                {"released_at": now, "release_reason": "offline"}
            )
            self.env["flousflow.whatsapp.audit.event"].sudo().create(
                {
                    "company_id": conversation.company_id.id,
                    "event_type": "offline_reassignment",
                    "actor_user_id": previous_user.id,
                    "conversation_id": conversation.id,
                    "number_id": conversation.number_id.id,
                    "occurred_at": now,
                    "reason": "Assigned agent was not Online after the two-minute grace period.",
                }
            )
            conversation.write(
                {
                    "assigned_user_id": False,
                    "assigned_at": False,
                    "assignment_release_at": False,
                    "state": "unassigned",
                }
            )
            conversation.assign_available_agent()
        return True

    def unlink(self):
        if any(conversation.lock_ids for conversation in self) and not self.env.su:
            raise AccessError(_("Conversations with history cannot be deleted."))
        return super().unlink()
