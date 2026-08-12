from odoo import Command, fields
from odoo.tests import tagged

from .common import WhatsAppCommon


@tagged("post_install", "-at_install", "flousflow_whatsapp")
class TestPartnerStatement(WhatsAppCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent.group_ids = [Command.link(cls.env.ref("account.group_account_user").id)]
        cls.partner = cls.env["res.partner"].create({
            "name": "Statement Partner",
            "company_id": cls.company.id,
        })
        cls.receivable = cls.env["account.account"].search([
            ("account_type", "=", "asset_receivable"),
            ("company_ids", "in", [cls.company.id]),
            ("reconcile", "=", True),
        ], limit=1)
        cls.payable = cls.env["account.account"].search([
            ("account_type", "=", "liability_payable"),
            ("company_ids", "in", [cls.company.id]),
            ("reconcile", "=", True),
        ], limit=1)
        cls.journal = cls.env["account.journal"].search([
            ("type", "=", "sale"),
            ("company_id", "=", cls.company.id),
        ], limit=1)

    def _require_accounting(self):
        if not self.receivable or not self.journal:
            self.skipTest("No receivable account or sale journal available in the test database.")

    def _post_entry(self, amount, date, reference):
        """Post a balanced journal entry with a receivable line for the partner.

        Journal entries with explicit debit/credit are the most reliable way to
        seed receivable history for the statement (direct invoice creation in
        Odoo 19 requires a fuller sale/tax setup).
        """
        income = self.env["account.account"].search([
            ("account_type", "=", "income"),
            ("company_ids", "in", [self.company.id]),
        ], limit=1)
        offset_account = income.id or self.receivable.id
        move = self.env["account.move"].create({
            "move_type": "entry",
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "journal_id": self.journal.id,
            "date": date,
            "line_ids": [
                Command.create({
                    "name": reference,
                    "account_id": self.receivable.id,
                    "partner_id": self.partner.id,
                    "debit": amount,
                }),
                Command.create({
                    "name": reference,
                    "account_id": offset_account,
                    "credit": amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _post_entry_payable(self, amount, date, reference):
        """Post a balanced entry with a credit to the payable account."""
        if not self.payable:
            self.skipTest("No payable account available in the test database.")
        expense = self.env["account.account"].search([
            ("account_type", "=", "expense"),
            ("company_ids", "in", [self.company.id]),
        ], limit=1)
        offset_account = expense.id or self.payable.id
        move = self.env["account.move"].create({
            "move_type": "entry",
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "journal_id": self.journal.id,
            "date": date,
            "line_ids": [
                Command.create({
                    "name": reference,
                    "account_id": offset_account,
                    "debit": amount,
                }),
                Command.create({
                    "name": reference,
                    "account_id": self.payable.id,
                    "partner_id": self.partner.id,
                    "credit": amount,
                }),
            ],
        })
        move.action_post()
        return move

    def test_statement_both_reports_receivable_and_payable(self):
        """Combined statement must expose separate receivable/payable positions."""
        self._require_accounting()
        self._post_entry(1000.0, fields.Date.today().replace(month=1, day=10), "Invoice A")
        self._post_entry(500.0, fields.Date.today().replace(month=2, day=15), "Invoice B")
        self._post_entry_payable(300.0, fields.Date.today().replace(month=1, day=20), "Bill A")
        self._post_entry_payable(200.0, fields.Date.today().replace(month=2, day=25), "Bill B")
        wizard = self.env["flousflow.partner.statement.wizard"].with_user(
            self.agent
        ).create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date_from": fields.Date.today().replace(month=2, day=1),
            "date_to": fields.Date.today().replace(month=2, day=28),
            "account_type": "both",
        })
        wizard.action_preview()
        # January entries only, split by type (payable shows as negative balance).
        self.assertEqual(wizard.opening_receivable, 1000.0)
        self.assertEqual(wizard.opening_payable, -300.0)
        # February entries added.
        self.assertEqual(wizard.closing_receivable, 1500.0)
        self.assertEqual(wizard.closing_payable, -500.0)
        # Combined positions still hold (receivable minus payable).
        self.assertEqual(wizard.opening_balance, 1000.0 - 300.0)
        self.assertEqual(wizard.closing_balance, 1500.0 - 500.0)

    def test_statement_computes_opening_and_closing(self):
        self._require_accounting()
        self._post_entry(1000.0, fields.Date.today().replace(month=1, day=10), "Invoice A")
        self._post_entry(500.0, fields.Date.today().replace(month=2, day=15), "Invoice B")
        wizard = self.env["flousflow.partner.statement.wizard"].with_user(
            self.agent
        ).create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date_from": fields.Date.today().replace(month=2, day=1),
            "date_to": fields.Date.today().replace(month=2, day=28),
            "account_type": "receivable",
        })
        wizard.action_preview()
        self.assertEqual(wizard.opening_balance, 1000.0)
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids[0].debit, 500.0)
        self.assertEqual(wizard.closing_balance, 1500.0)
        self.assertEqual(wizard.total_debit, 500.0)

    def test_statement_rejects_invalid_period(self):
        self._require_accounting()
        wizard = self.env["flousflow.partner.statement.wizard"].with_user(
            self.agent
        ).create({
            "partner_id": self.partner.id,
            "company_id": self.company.id,
            "date_from": fields.Date.today(),
            "date_to": fields.Date.today().replace(day=1) - __import__("datetime").timedelta(days=1),
            "account_type": "receivable",
        })
        with self.assertRaises(Exception):
            wizard.action_preview()
