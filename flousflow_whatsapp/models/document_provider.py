from odoo import models, _
from odoo.exceptions import ValidationError


class FlousflowWhatsappDocumentProvider(models.AbstractModel):
    _name = "flousflow.whatsapp.document.provider"
    _description = "WhatsApp Document Provider"

    def get_actions(self, conversation):
        """Return the document actions available in this conversation."""
        conversation.ensure_one()
        actions = []
        user = self.env.user
        if not conversation.partner_id:
            return actions
        if user.has_group("sales_team.group_sale_salesman"):
            actions.append({
                "key": "quotation",
                "label": _("Quotation"),
                "icon": "fa fa-file-text-o",
            })
        if user.has_group("account.group_account_user"):
            actions.append({
                "key": "partner_statement",
                "label": _("Customer Statement"),
                "icon": "fa fa-list-alt",
            })
        return actions

    def open_wizard(self, provider_key, conversation):
        """Open the wizard matching the selected provider key."""
        conversation.ensure_one()
        if provider_key == "quotation":
            return {
                "type": "ir.actions.act_window",
                "name": _("Send Quotation by WhatsApp"),
                "res_model": "flousflow.whatsapp.sale.document.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {"default_conversation_id": conversation.id},
            }
        if provider_key == "partner_statement":
            return {
                "type": "ir.actions.act_window",
                "name": _("Send Customer Statement by WhatsApp"),
                "res_model": "flousflow.whatsapp.statement.document.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {"default_conversation_id": conversation.id},
            }
        raise ValidationError(_("The selected WhatsApp document provider is unavailable."))
