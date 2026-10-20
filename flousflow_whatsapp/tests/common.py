from odoo import Command
from odoo.tests.common import TransactionCase


class WhatsAppCommon(TransactionCase):
    @classmethod
    def _relax_orphan_not_null_columns(cls):
        """Relax NOT NULL columns on ``res_company`` that belong to modules
        outside this module's dependency graph.

        When tests run with a restricted registry (``-u MODULE`` /
        ``--test-tags``), those columns stay ``NOT NULL`` in the database but
        are absent from the loaded model, so creating a company raises a
        ``NotNullViolation``. This is unrelated to the WhatsApp suite, so we
        accommodate it in the test database.
        """
        cls.env.cr.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'res_company'
               AND is_nullable = 'NO'
               AND column_default IS NULL
            """
        )
        known = set(cls.env["res.company"]._fields)
        for (column,) in cls.env.cr.fetchall():
            if column not in known:
                cls.env.cr.execute(
                    'ALTER TABLE res_company ALTER COLUMN "%s" DROP NOT NULL'
                    % column
                )

    @classmethod
    def _make_company(cls, name):
        """Create a company robustly across Odoo 20 module combinations.

        ``account``/``stock_account`` add required, NOT NULL columns to
        ``res.company`` (``inventory_period``, ``security_lead``). Fill the ones
        that are present in the loaded model and relax the rest.
        """
        values = {"name": name}
        company_model = cls.env["res.company"]
        if "inventory_period" in company_model._fields:
            values["inventory_period"] = "monthly"
        if "security_lead" in company_model._fields:
            values["security_lead"] = 3.0
        cls._relax_orphan_not_null_columns()
        return company_model.create(values)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Team = cls.env["flousflow.whatsapp.team"]
        cls.Number = cls.env["flousflow.whatsapp.number"]
        cls.NumberMember = cls.env["flousflow.whatsapp.number.member"]
        cls.Conversation = cls.env["flousflow.whatsapp.conversation"]

        cls.company = cls.env.company
        cls.other_company = cls._make_company("Other WhatsApp Company")
        agent_group = cls.env.ref("flousflow_whatsapp.group_whatsapp_agent")
        cls.agent = cls.env["res.users"].create(
            {
                "name": "WhatsApp Agent",
                "login": "whatsapp-agent-security-test",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([agent_group.id])],
            }
        )
        cls.agent_b = cls.env["res.users"].create(
            {
                "name": "WhatsApp Agent B",
                "login": "whatsapp-agent-b-security-test",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([agent_group.id])],
            }
        )
        supervisor_group = cls.env.ref("flousflow_whatsapp.group_whatsapp_supervisor")
        cls.supervisor = cls.env["res.users"].create(
            {
                "name": "WhatsApp Supervisor",
                "login": "whatsapp-supervisor-security-test",
                "company_id": cls.company.id,
                "company_ids": [Command.set([cls.company.id])],
                "group_ids": [Command.set([supervisor_group.id])],
            }
        )
        cls.team = cls.Team.create(
            {
                "name": "Sales",
                "company_id": cls.company.id,
                "member_ids": [Command.set([cls.agent.id, cls.agent_b.id])],
                "supervisor_ids": [Command.set([cls.supervisor.id])],
            }
        )
        cls.number = cls.Number.create(
            {
                "name": "Sales Main",
                "phone_number": "+201000000001",
                "company_id": cls.company.id,
                "primary_team_id": cls.team.id,
            }
        )
        cls.other_team = cls.Team.create(
            {"name": "Other Team", "company_id": cls.other_company.id}
        )
        cls.other_number = cls.Number.create(
            {
                "name": "Other Company Number",
                "phone_number": "+201000000002",
                "company_id": cls.other_company.id,
                "primary_team_id": cls.other_team.id,
            }
        )

    @classmethod
    def _set_presence(cls, user, status):
        if status in {"busy", "offline"}:
            user.manual_im_status = status
            if status == "offline" and user.presence_ids:
                user.presence_ids.status = "offline"
            return
        user.manual_im_status = False if status == "online" else status
        cls.env["mail.presence"]._update_presence(user, inactivity_period=0)

    def _new_conversation(self, assigned_user=None, state="unassigned"):
        return self.Conversation.create(
            {
                "company_id": self.company.id,
                "number_id": self.number.id,
                "team_id": self.team.id,
                "customer_phone_normalized": "+201111111111",
                "assigned_user_id": assigned_user.id if assigned_user else False,
                "state": state,
            }
        )
