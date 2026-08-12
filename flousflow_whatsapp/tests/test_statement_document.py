from unittest.mock import patch

from odoo import Command, fields

from odoo.addons.flousflow_whatsapp.tests.common import WhatsAppCommon


class TestWhatsappStatementDocument(WhatsAppCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent.group_ids = [Command.link(cls.env.ref("account.group_account_user").id)]
        cls.partner = cls.env["res.partner"].create({
            "name": "Statement Customer",
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

    def test_provider_is_available_to_accountant(self):
        actions = self.env["flousflow.whatsapp.document.provider"].with_user(
            self.agent
        ).get_actions(self.conversation.with_user(self.agent))
        self.assertIn("partner_statement", [action["key"] for action in actions])

    def test_authorized_statement_pdf_is_queued(self):
        conversation = self.conversation.with_user(self.agent)
        conversation.acquire_write_lock()
        wizard = self.env["flousflow.whatsapp.statement.document.wizard"].with_user(
            self.agent
        ).create({
            "conversation_id": conversation.id,
            "date_from": fields.Date.start_of(fields.Date.today(), "month"),
            "date_to": fields.Date.today(),
            "caption": "Your statement",
        })
        statement_model = type(self.env["flousflow.partner.statement.wizard"])
        report_model = type(self.env["ir.actions.report"])
        with patch.object(statement_model, "action_preview", return_value=True), patch.object(
            report_model, "_render_qweb_pdf", return_value=(b"%PDF-1.4\n", "pdf")
        ):
            wizard.action_send()
        message = self.env["flousflow.whatsapp.message"].search([
            ("conversation_id", "=", conversation.id),
            ("source", "=", "odoo"),
        ], limit=1)
        self.assertEqual(message.message_type, "document")
        self.assertEqual(message.body, "Your statement")
        self.assertEqual(message.attachment_id.mimetype, "application/pdf")
