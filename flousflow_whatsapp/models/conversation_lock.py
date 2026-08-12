from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


LOCK_LEASE_SECONDS = 45


class FlousflowWhatsappConversationLock(models.Model):
    _name = "flousflow.whatsapp.conversation.lock"
    _description = "Flous Flow WhatsApp Conversation Lock"
    _order = "acquired_at desc, id desc"
    _check_company_auto = True

    conversation_id = fields.Many2one(
        "flousflow.whatsapp.conversation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="conversation_id.company_id",
        store=True,
        index=True,
    )
    number_id = fields.Many2one(
        related="conversation_id.number_id",
        store=True,
        index=True,
    )
    owner_user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="restrict",
        index=True,
        check_company=True,
    )
    acquired_at = fields.Datetime(required=True, default=fields.Datetime.now)
    heartbeat_at = fields.Datetime(required=True, default=fields.Datetime.now)
    expires_at = fields.Datetime(required=True, index=True)
    released_at = fields.Datetime(index=True)
    release_reason = fields.Selection(
        [
            ("close", "Composer Closed"),
            ("timeout", "Lease Timeout"),
            ("offline", "Agent Offline"),
            ("transfer", "Conversation Transferred"),
            ("takeover", "Supervisor Takeover"),
            ("external_reply", "Reply Sent from WhatsApp Phone"),
        ]
    )
    takeover_by_id = fields.Many2one("res.users", ondelete="set null")
    takeover_reason = fields.Text()

    _active_lock_unique = models.UniqueIndex(
        "(conversation_id) WHERE released_at IS NULL"
    )

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for values in vals_list:
            values.setdefault("acquired_at", now)
            values.setdefault("heartbeat_at", now)
            values.setdefault("expires_at", now + timedelta(seconds=LOCK_LEASE_SECONDS))
        return super().create(vals_list)


class FlousflowWhatsappConversation(models.Model):
    _inherit = "flousflow.whatsapp.conversation"

    def claim_and_acquire_write_lock(self):
        """Assign an unassigned conversation to the current agent and lock it."""
        self.ensure_one()
        self.check_access("read")
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_agent"):
            raise AccessError(_("Only WhatsApp agents can claim conversations."))
        self.env.cr.execute(
            "SELECT id FROM flousflow_whatsapp_conversation WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["assigned_user_id", "state"])
        if self.state in {"resolved", "closed", "spam", "blocked"}:
            raise UserError(_("This conversation is no longer available for replies."))
        if self.assigned_user_id and self.assigned_user_id != self.env.user:
            raise UserError(
                _(
                    "%(user)s is assigned to this conversation.",
                    user=self.assigned_user_id.name,
                )
            )
        if not self.assigned_user_id:
            # The agent write rule intentionally only covers assigned records.
            # Escalate this single, row-locked assignment after all checks above.
            self.sudo().write(
                {
                    "assigned_user_id": self.env.user.id,
                    "assigned_at": fields.Datetime.now(),
                    "state": "open",
                }
            )
        self.acquire_write_lock()
        return self.get_write_lock_info()

    def _active_write_lock(self):
        self.ensure_one()
        return self.lock_ids.filtered(lambda lock: not lock.released_at)[:1]

    def acquire_write_lock(self):
        self.ensure_one()
        self.check_access("read")
        if self.assigned_user_id != self.env.user:
            raise AccessError(_("Only the assigned agent can reply to this conversation."))
        self.env.cr.execute(
            "SELECT id FROM flousflow_whatsapp_conversation WHERE id = %s FOR UPDATE",
            [self.id],
        )
        now = fields.Datetime.now()
        active_lock = self._active_write_lock()
        if active_lock and active_lock.expires_at <= now:
            active_lock.sudo().write(
                {"released_at": now, "release_reason": "timeout"}
            )
            active_lock = self.env["flousflow.whatsapp.conversation.lock"]
        if active_lock:
            if active_lock.owner_user_id != self.env.user:
                raise UserError(
                    _(
                        "%(user)s is already handling this conversation.",
                        user=active_lock.owner_user_id.name,
                    )
                )
            active_lock.sudo().write(
                {
                    "heartbeat_at": now,
                    "expires_at": now + timedelta(seconds=LOCK_LEASE_SECONDS),
                }
            )
            return active_lock
        return self.env["flousflow.whatsapp.conversation.lock"].create(
            {"conversation_id": self.id, "owner_user_id": self.env.user.id}
        )

    def heartbeat_write_lock(self):
        self.ensure_one()
        lock = self._active_write_lock()
        if not lock or lock.owner_user_id != self.env.user:
            raise UserError(_("You no longer own the conversation write lock."))
        now = fields.Datetime.now()
        lock.sudo().write(
            {
                "heartbeat_at": now,
                "expires_at": now + timedelta(seconds=LOCK_LEASE_SECONDS),
            }
        )
        return lock

    def _release_lock_for_external_reply(self, message):
        """Invalidate an Odoo composer after a reply is sent from the linked phone."""
        for conversation in self:
            if (
                message.conversation_id != conversation
                or message.direction != "outbound"
                or message.source != "whatsapp_device"
            ):
                continue
            lock = conversation._active_write_lock()
            if lock:
                lock.sudo().write(
                    {
                        "released_at": fields.Datetime.now(),
                        "release_reason": "external_reply",
                    }
                )
        return True

    def release_write_lock(self, reason="close"):
        self.ensure_one()
        if reason not in {
            "close", "timeout", "offline", "transfer", "takeover", "external_reply",
        }:
            raise UserError(_("Invalid conversation lock release reason."))
        lock = self._active_write_lock()
        if not lock:
            return True
        is_manager = self.env.user.has_group(
            "flousflow_whatsapp.group_whatsapp_supervisor"
        )
        if lock.owner_user_id != self.env.user and not is_manager:
            raise AccessError(_("Only the lock owner or a supervisor can release it."))
        lock.sudo().write(
            {"released_at": fields.Datetime.now(), "release_reason": reason}
        )
        return True

    def get_write_lock_info(self):
        self.ensure_one()
        self.check_access("read")
        lock = self._active_write_lock()
        assignment = {
            "assigned_user_id": self.assigned_user_id.id or False,
            "assigned_user_name": self.assigned_user_id.name or False,
            "assigned_to_me": self.assigned_user_id == self.env.user,
        }
        if not lock:
            return {"locked": False, "owned_by_me": False, **assignment}
        return {
            "locked": True,
            "owned_by_me": lock.owner_user_id == self.env.user,
            "owner_user_id": lock.owner_user_id.id,
            "owner_name": lock.owner_user_id.name,
            "acquired_at": fields.Datetime.to_string(lock.acquired_at),
            "expires_at": fields.Datetime.to_string(lock.expires_at),
            **assignment,
        }
