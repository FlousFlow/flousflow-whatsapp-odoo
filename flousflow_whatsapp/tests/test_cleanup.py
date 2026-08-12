from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from psycopg2 import IntegrityError
from unittest.mock import MagicMock, patch

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappCleanup(WhatsAppCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin_group = cls.env.ref("flousflow_whatsapp.group_whatsapp_admin")
        cls.whatsapp_admin = cls.env["res.users"].create({
            "name": "WhatsApp Cleanup Admin",
            "login": "whatsapp-cleanup-admin-test",
            "company_id": cls.company.id,
            "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([admin_group.id])],
        })

    def _wizard(self, number=None, **values):
        number = number or self.number
        return self.env["flousflow.whatsapp.cleanup.wizard"].with_user(
            self.whatsapp_admin
        ).create({"number_id": number.id, **values})

    def test_cleanup_requires_exact_confirmation(self):
        wizard = self._wizard(confirmation="DELETE wrong")
        with self.assertRaisesRegex(ValidationError, "exact cleanup confirmation"):
            wizard.action_cleanup()

    def test_connector_session_key_is_globally_unique(self):
        self.number.connector_session_key = "globally-unique-session"
        with self.assertRaises(IntegrityError):
            self.other_number.connector_session_key = "globally-unique-session"
            self.env.flush_all()

    def test_admin_can_start_self_hosted_connector_from_odoo(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "flousflow_whatsapp.connector_url", "http://connector.internal:8787"
        )
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"session_key":"sales","state":"connecting"}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.dict("os.environ", {"FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET": "test-secret"}), patch(
            "odoo.addons.flousflow_whatsapp.models.number.build_opener", return_value=opener
        ):
            result = self.number.with_user(self.whatsapp_admin).action_connector_connect()
        request = opener.open.call_args.args[0]
        self.assertIn("/sessions/", request.full_url)
        self.assertTrue(request.full_url.endswith("/connect"))
        self.assertTrue(request.headers.get("X-flousflow-signature"))
        self.assertEqual(self.number.state, "connecting")
        self.assertEqual(result["tag"], "display_notification")

    def test_non_admin_cannot_run_cleanup(self):
        wizard = self.env["flousflow.whatsapp.cleanup.wizard"].sudo().create({
            "number_id": self.number.id,
            "confirmation": f"DELETE {self.number.phone_normalized}",
        })
        with self.assertRaises(AccessError):
            wizard.with_user(self.agent).action_cleanup()

    def test_cleanup_is_number_scoped_and_audited(self):
        conversation = self._new_conversation(self.agent, state="open")
        message = self.env["flousflow.whatsapp.message"].sudo().create({
            "conversation_id": conversation.id,
            "direction": "inbound", "source": "customer", "message_type": "text",
            "body": "Wrong account history", "state": "received",
            "external_message_id": "cleanup-message",
        })
        other_conversation = self.Conversation.create({
            "company_id": self.other_company.id,
            "number_id": self.other_number.id,
            "team_id": self.other_team.id,
            "customer_phone_normalized": "+201222222222",
            "state": "unassigned",
        })
        wizard = self._wizard(
            confirmation=f"DELETE {self.number.phone_normalized}",
        )
        result = wizard.action_cleanup()
        self.assertFalse(conversation.exists())
        self.assertFalse(message.exists())
        self.assertTrue(other_conversation.exists())
        self.assertEqual(result["tag"], "display_notification")
        self.assertFalse(self.number.allow_inbound)
        self.assertFalse(self.number.allow_outbound)
        self.assertEqual(self.number.state, "disabled")
        with self.assertRaisesRegex(ValidationError, "Inbound synchronization is disabled"):
            self.env["flousflow.whatsapp.connector.event"].ingest_inbound({
                "number_id": self.number.id,
                "external_message_id": "must-not-resync-after-cleanup",
                "customer_phone_normalized": "+201011111111",
                "message_type": "text",
                "body": "Should be rejected",
            })
        self.assertTrue(self.env["flousflow.whatsapp.audit.event"].search([
            ("event_type", "=", "synchronized_data_cleanup"),
            ("number_id", "=", self.number.id),
        ]))

    def test_only_unused_module_created_contacts_are_deleted(self):
        removable = self.env["res.partner"].create({
            "name": "Temporary WhatsApp Contact",
            "phone": "+201033333333",
            "company_id": self.company.id,
            "whatsapp_created_by_module": True,
            "whatsapp_source_number_id": self.number.id,
        })
        protected = self.env["res.partner"].create({
            "name": "Existing Customer",
            "phone": "+201044444444",
            "company_id": self.company.id,
        })
        self.Conversation.create({
            "company_id": self.company.id, "number_id": self.number.id,
            "team_id": self.team.id, "partner_id": removable.id,
            "customer_phone_normalized": "+201033333333", "state": "unassigned",
        })
        self.Conversation.create({
            "company_id": self.company.id, "number_id": self.number.id,
            "team_id": self.team.id, "partner_id": protected.id,
            "customer_phone_normalized": "+201044444444", "state": "unassigned",
        })
        self._wizard(
            confirmation=f"DELETE {self.number.phone_normalized}",
            delete_module_contacts=True,
        ).action_cleanup()
        self.assertFalse(removable.exists())
        self.assertTrue(protected.exists())

    def test_unlinked_module_contact_is_deleted_but_business_contact_is_preserved(self):
        removable = self.env["res.partner"].create({
            "name": "Unlinked WhatsApp Contact",
            "company_id": self.company.id,
            "whatsapp_created_by_module": True,
            "whatsapp_source_number_id": self.number.id,
        })
        protected = self.env["res.partner"].create({
            "name": "WhatsApp Contact Used by CRM",
            "company_id": self.company.id,
            "whatsapp_created_by_module": True,
            "whatsapp_source_number_id": self.number.id,
        })
        self.env["crm.lead"].create({
            "name": "Protected opportunity",
            "partner_id": protected.id,
            "company_id": self.company.id,
        })
        self._wizard(
            confirmation=f"DELETE {self.number.phone_normalized}",
            delete_module_contacts=True,
        ).action_cleanup()
        self.assertFalse(removable.exists())
        self.assertTrue(protected.exists())
