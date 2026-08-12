import uuid

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappSaleDocumentWizard(models.TransientModel):
    _name = "flousflow.whatsapp.sale.document.wizard"
    _description = "Send Quotation by WhatsApp"

    conversation_id = fields.Many2one(
        "flousflow.whatsapp.conversation", required=True, ondelete="cascade"
    )
    company_id = fields.Many2one(related="conversation_id.company_id", readonly=True)
    partner_id = fields.Many2one(related="conversation_id.partner_id", readonly=True)
    commercial_partner_id = fields.Many2one(
        related="partner_id.commercial_partner_id", readonly=True
    )
    sale_order_id = fields.Many2one("sale.order", required=True, check_company=True)
    caption = fields.Text(default=lambda self: _("Please find your quotation attached."))

    @api.constrains("conversation_id", "sale_order_id")
    def _check_document_scope(self):
        for wizard in self:
            order = wizard.sale_order_id
            conversation = wizard.conversation_id
            if not order or not conversation:
                continue
            if order.company_id != conversation.company_id:
                raise ValidationError(_("The quotation and WhatsApp conversation must belong to one company."))
            if order.partner_id.commercial_partner_id != conversation.partner_id.commercial_partner_id:
                raise ValidationError(_("Select a quotation for this WhatsApp customer."))

    def action_send(self):
        self.ensure_one()
        conversation = self.conversation_id
        if conversation.assigned_user_id != self.env.user:
            raise AccessError(_("Only the assigned agent can send this quotation."))
        self.sale_order_id.check_access("read")
        pdf, _ = self.env["ir.actions.report"]._render_qweb_pdf(
            "sale.action_report_saleorder", [self.sale_order_id.id]
        )
        self.env["flousflow.whatsapp.message"].queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": str(uuid.uuid4()),
            "body": self.caption or "",
            "message_type": "document",
            "filename": f"{self.sale_order_id.name}.pdf",
            "mimetype": "application/pdf",
            "content": pdf,
        })
        return {"type": "ir.actions.act_window_close"}
