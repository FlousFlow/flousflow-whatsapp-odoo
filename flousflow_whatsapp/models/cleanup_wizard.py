from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappCleanupWizard(models.TransientModel):
    _name = "flousflow.whatsapp.cleanup.wizard"
    _description = "WhatsApp Synchronized Data Cleanup"

    number_id = fields.Many2one(
        "flousflow.whatsapp.number", required=True, readonly=True, ondelete="cascade"
    )
    company_id = fields.Many2one(related="number_id.company_id", readonly=True)
    conversation_count = fields.Integer(compute="_compute_counts")
    message_count = fields.Integer(compute="_compute_counts")
    contact_count = fields.Integer(compute="_compute_counts")
    delete_module_contacts = fields.Boolean(
        string="Delete unused contacts created by this module",
        help="Existing contacts and contacts used by CRM, Sales or Accounting are always preserved.",
    )
    disable_number_after_cleanup = fields.Boolean(
        string="Disable this number after cleanup",
        default=True,
        help="Stops inbound and outbound synchronization until an administrator verifies the correct pairing and re-enables it.",
    )
    confirmation = fields.Char(help="Enter the exact confirmation shown below.")
    expected_confirmation = fields.Char(compute="_compute_expected_confirmation")

    @api.depends("number_id")
    def _compute_expected_confirmation(self):
        for wizard in self:
            wizard.expected_confirmation = (
                f"DELETE {wizard.number_id.phone_normalized}" if wizard.number_id else ""
            )

    @api.depends("number_id")
    def _compute_counts(self):
        conversations = self.env["flousflow.whatsapp.conversation"].sudo()
        messages = self.env["flousflow.whatsapp.message"].sudo()
        partners = self.env["res.partner"].sudo()
        for wizard in self:
            number = wizard.number_id
            if not number:
                wizard.conversation_count = wizard.message_count = wizard.contact_count = 0
                continue
            wizard.conversation_count = conversations.search_count([("number_id", "=", number.id)])
            wizard.message_count = messages.search_count([("number_id", "=", number.id)])
            wizard.contact_count = partners.search_count([
                ("whatsapp_created_by_module", "=", True),
                ("whatsapp_source_number_id", "=", number.id),
            ])

    def _unused_module_contacts(self, partners, number):
        partners = partners.filtered(
            lambda partner: partner.whatsapp_created_by_module
            and partner.whatsapp_source_number_id == number
            and not partner.child_ids
            and not partner.user_ids
        )
        if not partners:
            return partners
        used_ids = set()
        for model_name, field_name in (
            ("flousflow.whatsapp.conversation", "partner_id"),
            ("crm.lead", "partner_id"),
            ("sale.order", "partner_id"),
            ("account.move", "partner_id"),
        ):
            used_ids.update(
                self.env[model_name].sudo().search([
                    (field_name, "in", partners.ids),
                ]).mapped(field_name).ids
            )
        return partners.filtered(lambda partner: partner.id not in used_ids)

    def action_cleanup(self):
        self.ensure_one()
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_admin"):
            raise AccessError(_("Only a WhatsApp administrator can clean synchronized data."))
        number = self.number_id.exists()
        if not number or number.company_id not in self.env.user.company_ids:
            raise AccessError(_("You cannot clean data for this WhatsApp number."))
        if (self.confirmation or "").strip() != self.expected_confirmation:
            raise ValidationError(_("Enter the exact cleanup confirmation before continuing."))

        conversations = self.env["flousflow.whatsapp.conversation"].sudo().search([
            ("number_id", "=", number.id),
        ])
        messages = self.env["flousflow.whatsapp.message"].sudo().search([
            ("number_id", "=", number.id),
        ])
        attachments = messages.attachment_id
        candidate_contacts = self.env["res.partner"].sudo().search([
            ("whatsapp_created_by_module", "=", True),
            ("whatsapp_source_number_id", "=", number.id),
        ])
        counts = {"conversations": len(conversations), "messages": len(messages), "contacts": 0}

        self.env["flousflow.whatsapp.connector.event"].sudo().search([
            ("number_id", "=", number.id),
        ]).unlink()
        conversations.lock_ids.sudo().unlink()
        messages.sudo().unlink()
        conversations.sudo().unlink()
        attachments.sudo().unlink()

        if self.delete_module_contacts:
            removable = self._unused_module_contacts(candidate_contacts, number)
            counts["contacts"] = len(removable)
            removable.sudo().unlink()

        number_values = {"connector_pending_events": 0, "last_error_summary": False}
        if self.disable_number_after_cleanup:
            number_values.update({
                "allow_inbound": False,
                "allow_outbound": False,
                "state": "disabled",
            })
        number.sudo().write(number_values)
        self.env["flousflow.whatsapp.audit.event"].sudo().create({
            "company_id": number.company_id.id,
            "event_type": "synchronized_data_cleanup",
            "actor_user_id": self.env.user.id,
            "number_id": number.id,
            "reason": _("Administrator confirmed cleanup for an incorrectly paired number."),
            "metadata_json": counts,
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp cleanup completed"),
                "message": _(
                    "Deleted %(messages)s messages, %(conversations)s conversations and "
                    "%(contacts)s unused module-created contacts.",
                    **counts,
                ),
                "type": "success",
                "sticky": True,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
