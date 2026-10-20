from odoo import fields, models, _
from odoo.exceptions import UserError


class FlousflowPartnerStatementWizard(models.TransientModel):
    _name = "flousflow.partner.statement.wizard"
    _description = "Partner Statement"

    partner_id = fields.Many2one(
        "res.partner", string="Partner", required=True, ondelete="cascade"
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        ondelete="cascade",
    )
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)
    account_type = fields.Selection(
        [
            ("receivable", "Customer / Receivable"),
            ("payable", "Vendor / Payable"),
            ("both", "Customer & Vendor"),
        ],
        string="Account Type",
        required=True,
        default="receivable",
    )
    target_move = fields.Selection(
        [("posted", "Posted Entries"), ("all", "All Entries")],
        string="Target Moves",
        required=True,
        default="posted",
    )
    include_reconciled = fields.Boolean(
        string="Include Reconciled Entries", default=True
    )

    line_ids = fields.One2many(
        "flousflow.partner.statement.line", "wizard_id", string="Statement Lines"
    )
    opening_balance = fields.Monetary(
        currency_field="currency_id", string="Opening Balance"
    )
    closing_balance = fields.Monetary(
        currency_field="currency_id", string="Closing Balance"
    )
    total_debit = fields.Monetary(currency_field="currency_id", string="Total Debit")
    total_credit = fields.Monetary(currency_field="currency_id", string="Total Credit")
    account_count = fields.Integer(string="Accounts", default=0)
    # Per-type positions, useful when "both" is selected (receivable vs payable).
    opening_receivable = fields.Monetary(
        currency_field="currency_id", string="Receivable Opening"
    )
    closing_receivable = fields.Monetary(
        currency_field="currency_id", string="Receivable Closing"
    )
    opening_payable = fields.Monetary(
        currency_field="currency_id", string="Payable Opening"
    )
    closing_payable = fields.Monetary(
        currency_field="currency_id", string="Payable Closing"
    )

    def _account_type_codes(self):
        return {
            "receivable": ("asset_receivable",),
            "payable": ("liability_payable",),
            "both": ("asset_receivable", "liability_payable"),
        }[self.account_type]

    def _get_accounts(self):
        self.ensure_one()
        # Odoo 20 uses ``company_ids`` (m2m) on account.account, not company_id.
        return self.env["account.account"].search(
            [
                ("company_ids", "in", [self.company_id.id]),
                ("account_type", "in", self._account_type_codes()),
                ("reconcile", "=", True),
            ]
        )

    def _base_domain(self, accounts=None):
        self.ensure_one()
        accounts = accounts or self._get_accounts()
        domain = [
            ("partner_id", "=", self.partner_id.commercial_partner_id.id),
            ("account_id", "in", accounts.ids),
            ("company_id", "=", self.company_id.id),
        ]
        if self.target_move == "posted":
            domain.append(("parent_state", "=", "posted"))
        return domain

    def _type_balance(self, account_type, before_date):
        """Balance (receivable/payable) strictly before ``before_date``."""
        accounts = self.env["account.account"].search(
            [
                ("company_ids", "in", [self.company_id.id]),
                ("account_type", "=", account_type),
                ("reconcile", "=", True),
            ]
        )
        domain = [
            ("partner_id", "=", self.partner_id.commercial_partner_id.id),
            ("account_id", "in", accounts.ids),
            ("company_id", "=", self.company_id.id),
            ("date", "<", before_date),
        ]
        if self.target_move == "posted":
            domain.append(("parent_state", "=", "posted"))
        grouped = self.env["account.move.line"]._read_group(
            domain, [], ["balance:sum"]
        )
        return grouped[0][0] if grouped else 0.0

    def _compute_statement(self):
        """Compute the statement and store its lines on the wizard."""
        self.ensure_one()
        if not self.date_from or not self.date_to or self.date_from > self.date_to:
            raise UserError(_("Start date must be before or equal to end date."))
        accounts = self._get_accounts()
        if not accounts:
            raise UserError(
                _(
                    "No reconcilable %(type)s accounts were found for this company.",
                    type=dict(
                        self._fields["account_type"].selection
                    ).get(self.account_type, self.account_type),
                )
            )
        domain = self._base_domain(accounts)
        # Opening balance: everything booked strictly before the start date.
        grouped = self.env["account.move.line"]._read_group(
            domain + [("date", "<", self.date_from)], [], ["balance:sum"]
        )
        opening = grouped[0][0] if grouped else 0.0
        # Period lines; push the reconciled filter to SQL when we do not want
        # reconciled entries so we avoid loading them into Python at all.
        period_domain = domain + [
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ]
        if not self.include_reconciled:
            period_domain.append(("reconciled", "=", False))
        period_lines = self.env["account.move.line"].search(
            period_domain, order="date, id"
        )
        shown = period_lines
        precision = self.currency_id.decimal_places
        running = opening
        vals_list = []
        for line in shown:
            running = round(running + line.balance, precision)
            vals_list.append(
                {
                    "wizard_id": self.id,
                    "date": line.date,
                    "move_name": line.move_id.name or line.ref or "",
                    "name": line.name or "",
                    "debit": line.debit,
                    "credit": line.credit,
                    "balance": running,
                }
            )
        # The lines are derived display data owned by this transient wizard.
        # Agents that can read the wizard may not hold create/unlink rights on
        # the line model, so manage it under sudo.
        self.line_ids.sudo().unlink()
        if vals_list:
            self.env["flousflow.partner.statement.line"].sudo().create(vals_list)
        self.opening_balance = opening
        self.closing_balance = running if shown else opening
        self.total_debit = sum(line.debit for line in shown)
        self.total_credit = sum(line.credit for line in shown)
        self.account_count = len(accounts)
        # Separate receivable / payable positions for the combined statement.
        if self.account_type == "both":
            closing_at = fields.Date.add(self.date_to, days=1)
            self.opening_receivable = self._type_balance(
                "asset_receivable", self.date_from
            )
            self.closing_receivable = self._type_balance(
                "asset_receivable", closing_at
            )
            self.opening_payable = self._type_balance(
                "liability_payable", self.date_from
            )
            self.closing_payable = self._type_balance(
                "liability_payable", closing_at
            )
        return True

    def action_preview(self):
        self.ensure_one()
        return self._compute_statement()


class FlousflowPartnerStatementLine(models.TransientModel):
    _name = "flousflow.partner.statement.line"
    _description = "Partner Statement Line"
    _order = "date, id"

    wizard_id = fields.Many2one(
        "flousflow.partner.statement.wizard", required=True, ondelete="cascade"
    )
    currency_id = fields.Many2one(related="wizard_id.currency_id", readonly=True)
    date = fields.Date(string="Date")
    move_name = fields.Char(string="Reference")
    name = fields.Char(string="Description")
    debit = fields.Monetary(currency_field="currency_id", string="Debit")
    credit = fields.Monetary(currency_field="currency_id", string="Credit")
    balance = fields.Monetary(currency_field="currency_id", string="Balance")
