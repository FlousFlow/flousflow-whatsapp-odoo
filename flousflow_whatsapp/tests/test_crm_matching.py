from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappCrmMatching(WhatsAppCommon):
    def test_existing_normalized_partner_is_reused(self):
        partner = self.env["res.partner"].create({
            "name": "Existing Customer", "phone": "+20 100 000 0000",
            "company_id": self.company.id,
        })
        found = self.env["res.partner"]._find_whatsapp_partner("+201000000000", self.company)
        self.assertEqual(found, partner)

    def test_partner_from_other_company_is_not_reused(self):
        self.env["res.partner"].create({
            "name": "Other Customer", "phone": "+20 101 111 1111",
            "company_id": self.other_company.id,
        })
        found = self.env["res.partner"]._find_whatsapp_partner("+201011111111", self.company)
        self.assertFalse(found)

    def test_inbound_message_links_existing_partner(self):
        partner = self.env["res.partner"].create({
            "name": "Inbound Customer", "phone": "+20 102 222 2222",
            "company_id": self.company.id,
        })
        message = self.env["flousflow.whatsapp.connector.event"].ingest_inbound({
            "number_id": self.number.id, "external_message_id": "crm-match-1",
            "customer_phone_normalized": "+201022222222", "message_type": "text", "body": "Hello",
        })
        self.assertEqual(message.conversation_id.partner_id, partner)
        self.assertEqual(partner.whatsapp_conversation_count, 1)

    def test_lead_action_filters_linked_conversations(self):
        lead = self.env["crm.lead"].create({"name": "WhatsApp Opportunity"})
        conversation = self._new_conversation()
        conversation.lead_id = lead
        self.assertEqual(lead.whatsapp_conversation_count, 1)
        self.assertEqual(lead.action_open_whatsapp_conversations()["domain"], [("lead_id", "=", lead.id)])
