from odoo import models, _
from odoo.exceptions import AccessError, UserError

from odoo.addons.flousflow_whatsapp.models.number import normalize_phone


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _whatsapp_customer_phone_choices(self):
        self.ensure_one()
        choices = []
        seen = set()
        partners = self.partner_id | self.partner_id.commercial_partner_id
        for partner in partners:
            for field_name, label in (("mobile", _("Mobile")), ("phone", _("Phone"))):
                if field_name not in partner._fields:
                    continue
                phone = normalize_phone(partner[field_name])
                if phone and phone not in seen:
                    choices.append((phone, _("%(label)s: %(phone)s", label=label, phone=phone)))
                    seen.add(phone)
        return choices

    def _whatsapp_available_numbers(self):
        self.ensure_one()
        numbers = self.env["flousflow.whatsapp.number"].search([
            ("company_id", "=", self.company_id.id),
            ("state", "=", "connected"),
            ("allow_outbound", "=", True),
            ("active", "=", True),
        ])
        return numbers.filtered(lambda number: number.user_can_access(self.env.user))

    def action_send_quotation_whatsapp(self):
        self.ensure_one()
        self.check_access("read")
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_agent"):
            raise AccessError(_("Only authorized WhatsApp agents can send quotations."))
        if not self._whatsapp_customer_phone_choices():
            raise UserError(_("Add a valid mobile or phone number to this customer first."))
        numbers = self._whatsapp_available_numbers()
        if not numbers:
            raise UserError(_("You do not have access to a connected WhatsApp number for this company."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Send Quotation by WhatsApp"),
            "res_model": "flousflow.whatsapp.sale.order.send.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "flousflow_whatsapp.view_whatsapp_sale_order_send_wizard_form"
            ).id,
            "target": "new",
            "context": {"default_sale_order_id": self.id},
        }
