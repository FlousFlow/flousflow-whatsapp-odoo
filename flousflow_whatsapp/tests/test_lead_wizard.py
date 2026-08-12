from odoo.exceptions import AccessError, ValidationError

from .common import WhatsAppCommon


class TestWhatsappLeadWizard(WhatsAppCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.conversation = cls.Conversation.create({
            "company_id": cls.company.id,
            "number_id": cls.number.id,
            "team_id": cls.team.id,
            "customer_phone_normalized": "+201111111111",
            "assigned_user_id": cls.agent.id,
            "state": "open",
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Ahmed Customer",
            "phone": cls.conversation.customer_phone_normalized,
            "company_id": cls.company.id,
        })
        cls.conversation.partner_id = cls.partner

    def _wizard(self, **values):
        defaults = {
            "conversation_id": self.conversation.id,
            "contact_name": "Ahmed Customer",
            "name": "WhatsApp - Ahmed Customer",
            "summary": "Customer needs an ERP quotation.",
            "notes": "Asked to call tomorrow.",
        }
        defaults.update(values)
        return self.env["flousflow.whatsapp.lead.wizard"].with_user(self.agent).create(defaults)

    def test_open_wizard_uses_explicit_form_view(self):
        action = self.conversation.with_user(self.agent).action_open_lead_wizard()
        view = self.env.ref("flousflow_whatsapp.view_whatsapp_lead_wizard_form")
        self.assertEqual(action["view_id"], view.id)
        self.assertEqual(action["views"], [(view.id, "form")])

    def test_unassigned_agent_cannot_open_create_lead_wizard(self):
        conversation = self._new_conversation()
        with self.assertRaises(AccessError):
            conversation.with_user(self.agent).action_open_lead_wizard()

    def test_non_assigned_agent_cannot_create_lead(self):
        wizard = self._wizard().with_user(self.agent_b)
        with self.assertRaises(AccessError):
            wizard.action_create_lead()

    def test_summary_is_required(self):
        with self.assertRaises(ValidationError):
            self._wizard(summary="   ").action_create_lead()

    def test_create_lead_links_partner_conversation_and_notes(self):
        action = self._wizard().action_create_lead()
        lead = self.conversation.lead_id
        self.assertTrue(lead)
        self.assertEqual(lead.partner_id, self.partner)
        self.assertEqual(lead.phone, self.conversation.customer_phone_normalized)
        self.assertIn("Customer needs an ERP quotation.", lead.description)
        self.assertIn("Asked to call tomorrow.", lead.description)
        self.assertEqual(action["res_id"], lead.id)

    def test_create_lead_creates_contact_when_conversation_is_unknown(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.customer_phone_normalized = "+201111111112"
        conversation.customer_display_name = "New WhatsApp Customer"
        wizard = self.env["flousflow.whatsapp.lead.wizard"].with_user(self.agent).create({
            "conversation_id": conversation.id,
            "contact_name": "Approved Customer Name",
            "name": "WhatsApp - Approved Customer Name",
            "email": "New.Customer@Example.COM",
            "summary": "Customer requested an ERP demo.",
        })
        wizard.action_create_lead()
        self.assertTrue(conversation.partner_id)
        self.assertEqual(conversation.partner_id.name, "Approved Customer Name")
        self.assertEqual(conversation.partner_id.phone, conversation.customer_phone_normalized)
        self.assertEqual(conversation.partner_id.email, "new.customer@example.com")
        self.assertEqual(conversation.lead_id.email_from, "new.customer@example.com")
        self.assertEqual(conversation.lead_id.partner_id, conversation.partner_id)

    def test_create_lead_reuses_existing_contact_by_email(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.customer_phone_normalized = "+201111111114"
        partner = self.env["res.partner"].create({
            "name": "Existing Email Contact",
            "phone": "+201000000001",
            "email": "Existing.Customer@Example.COM",
            "company_id": self.company.id,
        })
        wizard = self.env["flousflow.whatsapp.lead.wizard"].with_user(self.agent).create({
            "conversation_id": conversation.id,
            "contact_name": "Different WhatsApp Name",
            "name": "WhatsApp - Existing Customer",
            "email": "existing.customer@example.com",
            "summary": "Existing customer requested support.",
        })
        wizard.action_create_lead()
        self.assertEqual(conversation.partner_id, partner)
        self.assertEqual(conversation.lead_id.partner_id, partner)
        self.assertEqual(conversation.lead_id.email_from, "existing.customer@example.com")

    def test_phone_and_email_contact_conflict_blocks_lead(self):
        other_partner = self.env["res.partner"].create({
            "name": "Other Customer",
            "email": "other.customer@example.com",
            "company_id": self.company.id,
        })
        with self.assertRaisesRegex(ValidationError, "different contacts"):
            self._wizard(email=other_partner.email).action_create_lead()
        self.assertFalse(self.conversation.lead_id)

    def test_invalid_email_blocks_lead(self):
        with self.assertRaisesRegex(ValidationError, "valid customer email"):
            self._wizard(email="not-an-email").action_create_lead()
        self.assertFalse(self.conversation.lead_id)

    def test_other_company_email_is_not_reused(self):
        other_partner = self.env["res.partner"].create({
            "name": "Other Company Customer",
            "email": "same.customer@example.com",
            "company_id": self.other_company.id,
        })
        conversation = self._new_conversation(self.agent, state="open")
        conversation.customer_phone_normalized = "+201111111115"
        wizard = self.env["flousflow.whatsapp.lead.wizard"].with_user(self.agent).create({
            "conversation_id": conversation.id,
            "contact_name": "Current Company Customer",
            "name": "WhatsApp - Current Company Customer",
            "email": other_partner.email,
            "summary": "Customer requested a demo.",
        })
        wizard.action_create_lead()
        self.assertNotEqual(conversation.partner_id, other_partner)
        self.assertEqual(conversation.partner_id.company_id, self.company)

    def test_create_lead_reuses_contact_added_after_conversation_started(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.customer_phone_normalized = "+201111111113"
        partner = self.env["res.partner"].create({
            "name": "Existing Contact",
            "phone": conversation.customer_phone_normalized,
            "company_id": self.company.id,
        })
        wizard = self.env["flousflow.whatsapp.lead.wizard"].with_user(self.agent).create({
            "conversation_id": conversation.id,
            "contact_name": "Should Not Duplicate",
            "name": "WhatsApp - Existing Contact",
            "summary": "Existing customer asked for help.",
        })
        wizard.action_create_lead()
        self.assertEqual(conversation.partner_id, partner)
        self.assertEqual(conversation.lead_id.partner_id, partner)

    def test_second_lead_is_not_created_for_same_conversation(self):
        first_action = self._wizard().action_create_lead()
        second_action = self._wizard(name="Duplicate").action_create_lead()
        self.assertEqual(second_action["res_id"], first_action["res_id"])

    def test_same_company_and_phone_reuses_existing_whatsapp_lead(self):
        first_action = self._wizard().action_create_lead()
        other = self.Conversation.create({
            "company_id": self.company.id,
            "number_id": self.number.id,
            "team_id": self.team.id,
            "customer_phone_normalized": self.conversation.customer_phone_normalized,
            "assigned_user_id": self.agent.id,
            "state": "open",
        })
        other.partner_id = self.partner
        action = other.with_user(self.agent).action_open_lead_wizard()
        self.assertEqual(action["res_model"], "crm.lead")
        self.assertEqual(action["res_id"], first_action["res_id"])
        self.assertEqual(other.lead_id.id, first_action["res_id"])
