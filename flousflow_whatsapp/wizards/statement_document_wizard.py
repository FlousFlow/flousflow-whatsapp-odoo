import uuid

from odoo import fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappStatementDocumentWizard(models.TransientModel):
    _name = "flousflow.whatsapp.statement.document.wizard"
    _description = "Send Customer Statement by WhatsApp"

    conversation_id = fields.Many2one(
        "flousflow.whatsapp.conversation", required=True, ondelete="cascade"
    )
    company_id = fields.Many2one(related="conversation_id.company_id", readonly=True)
    partner_id = fields.Many2one(related="conversation_id.partner_id", readonly=True)
    date_from = fields.Date(
        required=True,
        default=lambda self: fields.Date.start_of(fields.Date.today(), "month"),
    )
    date_to = fields.Date(required=True, default=fields.Date.today)
    account_type = fields.Selection(
        [
            ("receivable", "Customer / Receivable"),
            ("payable", "Vendor / Payable"),
            ("both", "Customer & Vendor"),
        ],
        required=True,
        default="receivable",
    )
    target_move = fields.Selection(
        [("posted", "Posted Entries"), ("all", "All Entries")],
        required=True,
        default="posted",
    )
    include_reconciled = fields.Boolean(default=True)
    caption = fields.Text(default=lambda self: _("Please find your account statement attached."))

    def action_send(self):
        self.ensure_one()
        conversation = self.conversation_id
        if not self.date_from or not self.date_to or self.date_from > self.date_to:
            raise ValidationError(_("Start date must be before or equal to end date."))
        if conversation.assigned_user_id != self.env.user:
            raise AccessError(_("Only the assigned agent can send this statement."))
        statement = self.env["flousflow.partner.statement.wizard"].create({
            "partner_id": self.partner_id.commercial_partner_id.id,
            "company_id": self.company_id.id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "account_type": self.account_type,
            "target_move": self.target_move,
            "include_reconciled": self.include_reconciled,
        })
        statement.action_preview()
        pdf, _ = self.env["ir.actions.report"]._render_qweb_pdf(
            "flousflow_whatsapp.action_report_flousflow_partner_statement",
            [statement.id],
        )
        self.env["flousflow.whatsapp.message"].queue_outbound({
            "conversation_id": conversation.id,
            "client_idempotency_key": str(uuid.uuid4()),
            "body": self.caption or "",
            "message_type": "document",
            "filename": f"Statement-{self.partner_id.display_name}-{self.date_to}.pdf",
            "mimetype": "application/pdf",
            "content": pdf,
        })
        return {"type": "ir.actions.act_window_close"}
