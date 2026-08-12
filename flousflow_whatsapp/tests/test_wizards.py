from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestWhatsappWizards(WhatsAppCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        supervisor_group = cls.env.ref("flousflow_whatsapp.group_whatsapp_supervisor")
        cls.supervisor = cls.env["res.users"].create({
            "name": "WhatsApp Supervisor", "login": "whatsapp-supervisor-test",
            "company_id": cls.company.id, "company_ids": [Command.set([cls.company.id])],
            "group_ids": [Command.set([supervisor_group.id])],
        })
        cls.team.supervisor_ids = [Command.link(cls.supervisor.id)]

    def test_transfer_requires_exactly_one_target(self):
        conversation = self._new_conversation(self.agent, state="open")
        wizard = self.env["flousflow.whatsapp.transfer.wizard"].with_user(self.agent).create({
            "conversation_id": conversation.id, "reason": "Shift change",
        })
        with self.assertRaises(ValidationError):
            wizard.action_transfer()

    def test_assignee_can_transfer_to_authorized_agent(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        wizard = self.env["flousflow.whatsapp.transfer.wizard"].with_user(self.agent).create({
            "conversation_id": conversation.id, "target_user_id": self.agent_b.id,
            "reason": "Specialist required",
        })
        wizard.action_transfer()
        self.assertEqual(conversation.assigned_user_id, self.agent_b)
        self.assertEqual(conversation.lock_ids[-1].release_reason, "transfer")

    def test_agent_cannot_take_over(self):
        conversation = self._new_conversation(self.agent, state="open")
        with self.assertRaises(AccessError):
            self.env["flousflow.whatsapp.takeover.wizard"].with_user(self.agent).create({
                "conversation_id": conversation.id, "reason": "Not authorized",
            }).action_takeover()

    def test_supervisor_takeover_is_audited(self):
        conversation = self._new_conversation(self.agent, state="open")
        conversation.with_user(self.agent).acquire_write_lock()
        self.env["flousflow.whatsapp.takeover.wizard"].with_user(self.supervisor).create({
            "conversation_id": conversation.id, "reason": "Customer escalation",
        }).action_takeover()
        self.assertEqual(conversation.assigned_user_id, self.supervisor)
        audit = self.env["flousflow.whatsapp.audit.event"].search([
            ("conversation_id", "=", conversation.id), ("event_type", "=", "supervisor_takeover")
        ])
        self.assertEqual(len(audit), 1)
