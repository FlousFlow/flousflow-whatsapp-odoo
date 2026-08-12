from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError

from .number import normalize_phone


class ResPartner(models.Model):
    _inherit = "res.partner"

    whatsapp_created_by_module = fields.Boolean(
        copy=False, readonly=True,
        groups="flousflow_whatsapp.group_whatsapp_admin",
        help="Technical marker for contacts created from the WhatsApp CRM handoff.",
    )
    whatsapp_source_number_id = fields.Many2one(
        "flousflow.whatsapp.number", copy=False, readonly=True, ondelete="set null",
        groups="flousflow_whatsapp.group_whatsapp_admin",
    )
    whatsapp_phone_normalized = fields.Char(compute="_compute_whatsapp_phones", store=True, index=True)
    whatsapp_conversation_count = fields.Integer(compute="_compute_whatsapp_conversation_count")

    @api.depends("phone")
    def _compute_whatsapp_phones(self):
        for partner in self:
            partner.whatsapp_phone_normalized = normalize_phone(partner.phone)

    def _compute_whatsapp_conversation_count(self):
        grouped = self.env["flousflow.whatsapp.conversation"]._read_group(
            [("partner_id", "in", self.ids)], ["partner_id"], ["__count"]
        )
        counts = {partner.id: count for partner, count in grouped}
        for partner in self:
            partner.whatsapp_conversation_count = counts.get(partner.id, 0)

    @api.model
    def _find_whatsapp_partner(self, normalized_phone, company):
        normalized_phone = normalize_phone(normalized_phone)
        if not normalized_phone or not company:
            return self.browse()
        domain = [
            ("company_id", "in", [False, company.id]),
            ("whatsapp_phone_normalized", "=", normalized_phone),
        ]
        company_partner = self.search(domain + [("company_id", "=", company.id)], limit=1)
        return company_partner or self.search(domain + [("company_id", "=", False)], limit=1)

    @api.model
    def _resolve_whatsapp_crm_partner(self, phone, email, company):
        """Resolve a CRM customer without guessing when identifiers conflict."""
        if not company:
            return self.browse(), False

        normalized_phone = normalize_phone(phone)
        normalized_email = tools.email_normalize(email, strict=True) if email else False
        if email and not normalized_email:
            raise ValidationError(_("Enter one valid customer email address."))

        def _unique_company_match(field_name, value, label):
            if not value:
                return self.browse()
            company_matches = self.search([
                ("company_id", "=", company.id),
                (field_name, "=", value),
            ], limit=2)
            if len(company_matches) > 1:
                raise ValidationError(
                    _("More than one contact in this company uses the same %s. Merge or correct the contacts first.", label)
                )
            if company_matches:
                return company_matches
            shared_matches = self.search([
                ("company_id", "=", False),
                (field_name, "=", value),
            ], limit=2)
            if len(shared_matches) > 1:
                raise ValidationError(
                    _("More than one shared contact uses the same %s. Merge or correct the contacts first.", label)
                )
            return shared_matches

        phone_partner = _unique_company_match(
            "whatsapp_phone_normalized", normalized_phone, _("phone number")
        )
        email_partner = _unique_company_match(
            "email_normalized", normalized_email, _("email address")
        )
        if phone_partner and email_partner and phone_partner != email_partner:
            raise ValidationError(
                _(
                    "The phone number and email address belong to different contacts. "
                    "Correct the customer data before creating the lead."
                )
            )
        return phone_partner or email_partner, normalized_email

    def action_open_whatsapp_conversations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "WhatsApp Conversations",
            "res_model": "flousflow.whatsapp.conversation", "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
