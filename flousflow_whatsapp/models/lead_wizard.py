from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappLeadWizard(models.TransientModel):
    _name = "flousflow.whatsapp.lead.wizard"
    _description = "Create CRM Lead from WhatsApp"

    conversation_id = fields.Many2one(
        "flousflow.whatsapp.conversation", required=True, ondelete="cascade"
    )
    company_id = fields.Many2one(related="conversation_id.company_id", readonly=True)
    partner_id = fields.Many2one(related="conversation_id.partner_id", readonly=True)
    phone = fields.Char(related="conversation_id.customer_phone_normalized", readonly=True)
    email = fields.Char()
    contact_name = fields.Char(required=True)
    name = fields.Char(required=True)
    summary = fields.Text(required=True)
    notes = fields.Text()
    team_id = fields.Many2one("crm.team", check_company=True)
    user_id = fields.Many2one("res.users", check_company=True)
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Important"), ("2", "Very Important"), ("3", "Urgent")],
        default="0",
        required=True,
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        conversation = self.env["flousflow.whatsapp.conversation"].browse(
            values.get("conversation_id") or self.env.context.get("default_conversation_id")
        ).exists()
        if conversation:
            display_name = (
                conversation.partner_id.name
                or conversation.customer_display_name
                or conversation.customer_phone_normalized
            )
            values.setdefault("contact_name", display_name)
            values.setdefault("name", _("WhatsApp - %s", display_name))
            values.setdefault("user_id", conversation.assigned_user_id.id)
            values.setdefault("email", conversation.partner_id.email)
        return values

    def action_create_lead(self):
        self.ensure_one()
        conversation = self.conversation_id
        if not self.summary or not self.summary.strip():
            raise ValidationError(_("A conversation summary is required."))
        if not self.contact_name or not self.contact_name.strip():
            raise ValidationError(_("A contact name is required."))
        conversation._lock_whatsapp_lead_creation()
        conversation.invalidate_recordset(["lead_id"])
        conversation._link_existing_whatsapp_lead()
        if conversation.lead_id:
            lead = conversation.lead_id
        else:
            if conversation.assigned_user_id != self.env.user:
                raise AccessError(
                    _("Only the assigned agent can create a lead from this conversation.")
                )
            if conversation.company_id not in self.env.user.company_ids:
                raise AccessError(_("You cannot create a lead in this company."))
            matched_partner, normalized_email = self.env[
                "res.partner"
            ]._resolve_whatsapp_crm_partner(
                conversation.customer_phone_normalized,
                self.email,
                conversation.company_id,
            )
            if (
                conversation.partner_id
                and matched_partner
                and conversation.partner_id != matched_partner
            ):
                raise ValidationError(
                    _(
                        "The conversation contact conflicts with the entered phone or email. "
                        "Correct the customer data before creating the lead."
                    )
                )
            partner = conversation.partner_id or matched_partner
            if not partner:
                partner = self.env["res.partner"].create({
                    "name": self.contact_name.strip(),
                    "phone": conversation.customer_phone_normalized,
                    "email": normalized_email or False,
                    "company_id": conversation.company_id.id,
                })
                # These cleanup markers are intentionally admin-only fields. The
                # agent still creates the contact under their own access rights;
                # elevate only the narrow technical marker update afterwards.
                partner.sudo().write({
                    "whatsapp_created_by_module": True,
                    "whatsapp_source_number_id": conversation.number_id.id,
                })
            description = Markup("<p><strong>%s</strong></p><p>%s</p>") % (
                _("WhatsApp conversation summary"),
                self.summary.strip(),
            )
            if self.notes and self.notes.strip():
                description += Markup("<p><strong>%s</strong></p><p>%s</p>") % (
                    _("Agent notes"),
                    self.notes.strip(),
                )
            description += Markup("<p>%s: %s</p>") % (_("WhatsApp conversation"), conversation.name)
            lead = self.env["crm.lead"].create({
                "name": self.name,
                "type": "lead",
                "partner_id": partner.id,
                "contact_name": partner.name,
                "phone": conversation.customer_phone_normalized,
                "email_from": normalized_email or partner.email_normalized or False,
                "description": description,
                "company_id": conversation.company_id.id,
                "team_id": self.team_id.id,
                "user_id": self.user_id.id,
                "priority": self.priority,
            })
            conversation.write({"partner_id": partner.id, "lead_id": lead.id})
            conversation.message_post(
                body=_("CRM lead %s was created from this conversation.", lead.display_name)
            )
            conversation._notify_realtime("conversation")
        return {
            "type": "ir.actions.act_window",
            "name": _("CRM Lead"),
            "res_model": "crm.lead",
            "res_id": lead.id,
            "view_mode": "form",
        }
