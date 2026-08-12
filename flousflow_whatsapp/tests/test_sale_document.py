from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError

from odoo.addons.flousflow_whatsapp.tests.common import WhatsAppCommon


class TestWhatsappSaleDocument(WhatsAppCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent.group_ids = [Command.link(cls.env.ref("sales_team.group_sale_salesman").id)]
        cls.partner = cls.env["res.partner"].create({
            "name": "Quotation Customer",
            "phone": "+201111111111",
            "company_id": cls.company.id,
        })
        cls.conversation = cls.Conversation.create({
            "company_id": cls.company.id,
            "number_id": cls.number.id,
            "team_id": cls.team.id,
            "partner_id": cls.partner.id,
            "customer_phone_normalized": "+201111111111",
            "assigned_user_id": cls.agent.id,
            "state": "open",
        })
        cls.order = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "company_id": cls.company.id,
            "user_id": cls.agent.id,
        })
        cls.number.state = "connected"

    def test_provider_is_available_to_salesperson(self):
        actions = self.env["flousflow.whatsapp.document.provider"].with_user(
            self.agent
        ).get_actions(self.conversation.with_user(self.agent))
        self.assertIn("quotation", [action["key"] for action in actions])

    def test_authorized_quotation_pdf_is_queued(self):
        conversation = self.conversation.with_user(self.agent)
        conversation.acquire_write_lock()
        wizard = self.env["flousflow.whatsapp.sale.document.wizard"].with_user(
            self.agent
        ).create({
            "conversation_id": conversation.id,
            "sale_order_id": self.order.id,
            "caption": "Your quotation",
        })
        report_model = type(self.env["ir.actions.report"])
        with patch.object(report_model, "_render_qweb_pdf", return_value=(b"%PDF-1.4\n", "pdf")):
            wizard.action_send()
        message = self.env["flousflow.whatsapp.message"].search([
            ("conversation_id", "=", conversation.id),
            ("source", "=", "odoo"),
        ], limit=1)
        self.assertEqual(message.message_type, "document")
        self.assertEqual(message.body, "Your quotation")
        self.assertEqual(message.attachment_id.mimetype, "application/pdf")

    def test_sale_order_action_autoselects_single_authorized_number(self):
        action = self.order.with_user(self.agent).action_send_quotation_whatsapp()
        wizard = self.env["flousflow.whatsapp.sale.order.send.wizard"].with_user(
            self.agent
        ).with_context(**action["context"]).create({})
        self.assertEqual(wizard.sale_order_id, self.order)
        self.assertEqual(wizard.number_id, self.number)
        self.assertEqual(wizard.customer_phone, "+201111111111")

    def test_multiple_authorized_numbers_are_available_for_selection(self):
        second_number = self.Number.create({
            "name": "Sales Secondary",
            "phone_number": "+201000000099",
            "company_id": self.company.id,
            "primary_team_id": self.team.id,
            "state": "connected",
        })
        Wizard = self.env["flousflow.whatsapp.sale.order.send.wizard"].with_user(
            self.agent
        ).with_context(default_sale_order_id=self.order.id)
        defaults = Wizard.default_get(["sale_order_id", "number_id", "customer_phone"])
        self.assertNotIn("number_id", defaults)
        wizard = Wizard.create({"number_id": second_number.id})
        self.assertEqual(wizard.allowed_number_ids, self.number | second_number)
        self.assertEqual(wizard.number_id, second_number)

    def test_direct_send_creates_conversation_queues_pdf_and_marks_sent(self):
        wizard = self.env["flousflow.whatsapp.sale.order.send.wizard"].with_user(
            self.agent
        ).with_context(default_sale_order_id=self.order.id).create({})
        report_model = type(self.env["ir.actions.report"])
        with patch.object(report_model, "_render_qweb_pdf", return_value=(b"%PDF-1.4\n", "pdf")):
            wizard.action_send()
        conversation = self.Conversation.search([
            ("number_id", "=", self.number.id),
            ("customer_phone_normalized", "=", "+201111111111"),
        ], limit=1)
        message = self.env["flousflow.whatsapp.message"].search([
            ("conversation_id", "=", conversation.id),
            ("source", "=", "odoo"),
        ], limit=1)
        self.assertEqual(conversation.assigned_user_id, self.agent)
        self.assertEqual(message.message_type, "document")
        self.assertEqual(message.author_user_id, self.agent)
        self.assertEqual(self.order.state, "sent")
        self.assertFalse(conversation._active_write_lock())

    def test_direct_send_rejects_conversation_owned_by_another_agent(self):
        conversation = self.conversation
        conversation.assigned_user_id = self.agent_b
        wizard = self.env["flousflow.whatsapp.sale.order.send.wizard"].with_user(
            self.agent
        ).with_context(default_sale_order_id=self.order.id).create({})
        with self.assertRaises(UserError):
            wizard.action_send()

    def test_direct_action_requires_customer_phone(self):
        self.partner.phone = False
        with self.assertRaises(UserError):
            self.order.with_user(self.agent).action_send_quotation_whatsapp()
