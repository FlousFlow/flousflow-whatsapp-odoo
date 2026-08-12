import uuid

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class FlousflowWhatsappSaleOrderSendWizard(models.TransientModel):
    _name = "flousflow.whatsapp.sale.order.send.wizard"
    _description = "Send Sale Quotation by WhatsApp"

    sale_order_id = fields.Many2one("sale.order", required=True, readonly=True)
    company_id = fields.Many2one(related="sale_order_id.company_id", readonly=True)
    partner_id = fields.Many2one(related="sale_order_id.partner_id", readonly=True)
    allowed_number_ids = fields.Many2many(
        "flousflow.whatsapp.number", compute="_compute_allowed_number_ids"
    )
    number_id = fields.Many2one(
        "flousflow.whatsapp.number", required=True, check_company=True
    )
    customer_phone = fields.Selection(
        selection="_selection_customer_phone", required=True, string="Customer WhatsApp Number"
    )
    caption = fields.Text(default=lambda self: _("Please find your quotation attached."))

    @api.depends("sale_order_id")
    def _compute_allowed_number_ids(self):
        for wizard in self:
            wizard.allowed_number_ids = wizard.sale_order_id._whatsapp_available_numbers()

    @api.model
    def _selection_customer_phone(self):
        order_id = self.env.context.get("default_sale_order_id")
        order = self.env["sale.order"].browse(order_id).exists()
        return order._whatsapp_customer_phone_choices() if order else []

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        order = self.env["sale.order"].browse(values.get("sale_order_id")).exists()
        if not order:
            return values
        numbers = order._whatsapp_available_numbers()
        phones = order._whatsapp_customer_phone_choices()
        if len(numbers) == 1:
            values["number_id"] = numbers.id
        if len(phones) == 1:
            values["customer_phone"] = phones[0][0]
        return values

    @api.constrains("sale_order_id", "number_id", "customer_phone")
    def _check_send_scope(self):
        for wizard in self:
            if wizard.number_id and wizard.number_id not in wizard.sale_order_id._whatsapp_available_numbers():
                raise ValidationError(_("Select a connected WhatsApp number available to you."))
            allowed_phones = dict(wizard.sale_order_id._whatsapp_customer_phone_choices())
            if wizard.customer_phone and wizard.customer_phone not in allowed_phones:
                raise ValidationError(_("Select a WhatsApp number registered on this customer."))

    def _get_or_create_conversation(self):
        self.ensure_one()
        conversation_model = self.env["flousflow.whatsapp.conversation"]
        conversation = conversation_model.search([
            ("number_id", "=", self.number_id.id),
            ("customer_phone_normalized", "=", self.customer_phone),
            ("state", "not in", ["closed", "spam", "blocked"]),
        ], order="last_message_at desc, id desc", limit=1)
        if not conversation:
            conversation = conversation_model.sudo().create({
                "company_id": self.company_id.id,
                "number_id": self.number_id.id,
                "team_id": self.number_id.primary_team_id.id,
                "partner_id": self.partner_id.id,
                "customer_phone_normalized": self.customer_phone,
                "assigned_user_id": self.env.user.id,
                "assigned_at": fields.Datetime.now(),
                "state": "open",
            })
        return conversation.with_user(self.env.user)

    def action_send(self):
        self.ensure_one()
        self.sale_order_id.check_access("read")
        if self.number_id not in self.sale_order_id._whatsapp_available_numbers():
            raise AccessError(_("You are not allowed to use this WhatsApp number."))
        conversation = self._get_or_create_conversation()
        active_lock = conversation._active_write_lock()
        lock_was_owned = bool(
            active_lock
            and active_lock.owner_user_id == self.env.user
            and active_lock.expires_at > fields.Datetime.now()
        )
        acquired = False
        try:
            conversation.claim_and_acquire_write_lock()
            acquired = True
            pdf, _report_format = self.env["ir.actions.report"]._render_qweb_pdf(
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
            if self.sale_order_id.state == "draft":
                self.sale_order_id.action_quotation_sent()
        finally:
            if acquired and not lock_was_owned:
                conversation.release_write_lock()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": _("Quotation queued for delivery to %(phone)s.", phone=self.customer_phone),
                "type": "success",
                "sticky": False,
            },
        }
