import json
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from ..controllers.signing import ConnectorRequestError, sign_connector_request


class _NoConnectorRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def normalize_phone(value):
    """Normalize a phone number to a stable international-looking key."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return False
    return f"+{digits}"


class FlousflowWhatsappNumber(models.Model):
    _name = "flousflow.whatsapp.number"
    _description = "Flous Flow WhatsApp Number"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "company_id, name, id"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    phone_number = fields.Char(required=True, tracking=True)
    phone_normalized = fields.Char(
        required=True,
        index=True,
        readonly=True,
        copy=False,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
    )
    primary_team_id = fields.Many2one(
        "flousflow.whatsapp.team",
        required=True,
        check_company=True,
        tracking=True,
    )
    allowed_team_ids = fields.Many2many(
        "flousflow.whatsapp.team",
        "flousflow_whatsapp_number_team_rel",
        "number_id",
        "team_id",
        string="Additional Allowed Teams",
        check_company=True,
    )
    manager_user_id = fields.Many2one(
        "res.users",
        string="Number Manager",
        check_company=True,
        domain="[('share', '=', False)]",
    )
    member_line_ids = fields.One2many(
        "flousflow.whatsapp.number.member",
        "number_id",
        string="Direct User Rules",
    )
    allowed_user_ids = fields.Many2many(
        "res.users",
        "flousflow_whatsapp_number_allow_rel",
        "number_id",
        "user_id",
        readonly=True,
        copy=False,
    )
    denied_user_ids = fields.Many2many(
        "res.users",
        "flousflow_whatsapp_number_deny_rel",
        "number_id",
        "user_id",
        readonly=True,
        copy=False,
    )
    connector_session_key = fields.Char(
        copy=False,
        index=True,
        groups="flousflow_whatsapp.group_whatsapp_admin",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("qr", "Waiting for QR Scan"),
            ("connecting", "Connecting"),
            ("connected", "Connected"),
            ("reconnect", "Reconnect Required"),
            ("disabled", "Disabled"),
            ("error", "Error"),
        ],
        required=True,
        default="draft",
        tracking=True,
        index=True,
    )
    qr_image = fields.Binary(
        attachment=False,
        copy=False,
        groups="flousflow_whatsapp.group_whatsapp_admin",
    )
    last_connected_at = fields.Datetime(readonly=True, copy=False)
    last_error_summary = fields.Text(
        readonly=True,
        copy=False,
        groups="flousflow_whatsapp.group_whatsapp_admin",
    )
    connector_version = fields.Char(readonly=True, copy=False)
    connector_last_probe_at = fields.Datetime(readonly=True, copy=False)
    connector_pending_events = fields.Integer(readonly=True, copy=False)
    allow_inbound = fields.Boolean(default=True)
    allow_outbound = fields.Boolean(default=True)
    assignment_mode = fields.Selection(
        [
            ("least_open_round_robin", "Least Open, then Round Robin"),
            ("manual", "Manual Claim"),
        ],
        required=True,
        default="least_open_round_robin",
    )
    first_response_minutes = fields.Integer(required=True, default=5)
    reply_response_minutes = fields.Integer(required=True, default=10)
    escalation_minutes = fields.Integer(required=True, default=15)
    attachment_limit_mb = fields.Integer(required=True, default=10)
    enforce_service_window = fields.Boolean(default=True)
    service_window_hours = fields.Integer(required=True, default=24)
    create_lead_automatically = fields.Boolean(default=False)
    last_assigned_user_id = fields.Many2one(
        "res.users",
        string="Last Assigned Agent",
        copy=False,
        readonly=True,
        check_company=True,
    )
    active = fields.Boolean(default=True)

    _phone_company_unique = models.Constraint(
        "UNIQUE(company_id, phone_normalized)",
        "This WhatsApp number already exists for the company.",
    )
    _session_unique = models.Constraint(
        "UNIQUE(connector_session_key)",
        "The connector session key must be unique across all companies.",
    )
    _positive_sla = models.Constraint(
        "CHECK(first_response_minutes > 0 AND reply_response_minutes > 0 "
        "AND escalation_minutes > 0)",
        "SLA durations must be greater than zero.",
    )
    _positive_attachment_limit = models.Constraint(
        "CHECK(attachment_limit_mb > 0)",
        "The attachment limit must be greater than zero.",
    )
    _valid_service_window = models.Constraint(
        "CHECK(service_window_hours BETWEEN 1 AND 168)",
        "The customer service window must be between 1 and 168 hours.",
    )

    def _sync_direct_users(self):
        for number in self:
            active_lines = number.member_line_ids.filtered("active")
            allowed_ids = active_lines.filtered(
                lambda line: line.access_mode == "allow"
            ).user_id.ids
            denied_ids = active_lines.filtered(
                lambda line: line.access_mode == "deny"
            ).user_id.ids
            number.sudo().write(
                {
                    "allowed_user_ids": [Command.set(allowed_ids)],
                    "denied_user_ids": [Command.set(denied_ids)],
                }
            )

    def action_open_cleanup_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_admin"):
            raise AccessError(_("Only a WhatsApp administrator can clean synchronized data."))
        if self.company_id not in self.env.user.company_ids:
            raise AccessError(_("You cannot clean data for another company."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Clean Synchronized WhatsApp Data"),
            "res_model": "flousflow.whatsapp.cleanup.wizard",
            "view_mode": "form",
            "view_id": self.env.ref("flousflow_whatsapp.view_whatsapp_cleanup_wizard_form").id,
            "target": "new",
            "context": {"default_number_id": self.id},
        }

    def _connector_control(self, operation):
        self.ensure_one()
        if not self.env.user.has_group("flousflow_whatsapp.group_whatsapp_admin"):
            raise AccessError(_("Only a WhatsApp administrator can control connector sessions."))
        if self.company_id not in self.env.user.company_ids:
            raise AccessError(_("You cannot control a connector for another company."))
        if operation not in {"connect", "disconnect"}:
            raise ValidationError(_("Unsupported connector operation."))
        if not self.connector_session_key:
            self.connector_session_key = f"ffw_{secrets.token_urlsafe(24)}"
        base_url = (self.env["ir.config_parameter"].sudo().get_str(
            "flousflow_whatsapp.connector_url"
        ) or "").strip().rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise UserError(_("Set a valid HTTP(S) Connector URL in WhatsApp settings."))
        def connector_request(requested_operation):
            body = json.dumps({
                "session_key": self.connector_session_key,
                "operation": requested_operation,
            }, separators=(",", ":")).encode()
            try:
                signed_headers = sign_connector_request(body)
            except ConnectorRequestError as exc:
                raise UserError(_("Set FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET on the Odoo server.")) from exc
            request = Request(
                f"{base_url}/sessions/{quote(self.connector_session_key, safe='')}/{requested_operation}",
                data=body,
                headers={"Content-Type": "application/json", **signed_headers},
                method="POST",
            )
            try:
                with build_opener(_NoConnectorRedirects).open(request, timeout=15) as response:
                    return json.loads(response.read(65537))
            except HTTPError as exc:
                detail = exc.read(4096).decode(errors="replace")
                raise UserError(_(
                    "Connector rejected the %(operation)s request (%(code)s): %(detail)s",
                    operation=requested_operation, code=exc.code, detail=detail,
                )) from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise UserError(_("Could not reach a valid WhatsApp connector response: %s", exc)) from exc

        if operation == "connect":
            connector_request("register")
        result = connector_request(operation)
        state = result.get("state")
        if state in dict(self._fields["state"].selection):
            self.sudo().write({"state": state, "last_error_summary": False})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp connector"),
                "message": _("Session %(operation)s request accepted. Current state: %(state)s.", operation=operation, state=state or "unknown"),
                "type": "success",
                "sticky": False,
            },
        }

    def action_connector_connect(self):
        return self._connector_control("connect")

    def action_connector_disconnect(self):
        return self._connector_control("disconnect")

    @api.model_create_multi
    def create(self, vals_list):
        batch_keys = set()
        for values in vals_list:
            values.setdefault("connector_session_key", f"ffw_{secrets.token_urlsafe(24)}")
            values["phone_normalized"] = normalize_phone(values.get("phone_number"))
            if not values["phone_normalized"]:
                raise ValidationError(_("Enter a valid WhatsApp phone number."))
            company_id = values.get("company_id") or self.env.company.id
            key = (company_id, values["phone_normalized"])
            if key in batch_keys or self.search_count(
                [("company_id", "=", company_id), ("phone_normalized", "=", key[1])],
                limit=1,
            ):
                raise ValidationError(_("This WhatsApp number already exists for the company."))
            batch_keys.add(key)
        return super().create(vals_list)

    def write(self, values):
        values = dict(values)
        if "phone_number" in values:
            values["phone_normalized"] = normalize_phone(values["phone_number"])
            if not values["phone_normalized"]:
                raise ValidationError(_("Enter a valid WhatsApp phone number."))
        if "phone_normalized" in values or "company_id" in values:
            for number in self:
                company_id = values.get("company_id", number.company_id.id)
                phone_normalized = values.get("phone_normalized", number.phone_normalized)
                if self.search_count(
                    [
                        ("id", "!=", number.id),
                        ("company_id", "=", company_id),
                        ("phone_normalized", "=", phone_normalized),
                    ],
                    limit=1,
                ):
                    raise ValidationError(
                        _("This WhatsApp number already exists for the company.")
                    )
        return super().write(values)

    @api.constrains("company_id", "primary_team_id", "allowed_team_ids")
    def _check_team_companies(self):
        for number in self:
            teams = number.primary_team_id | number.allowed_team_ids
            if any(team.company_id != number.company_id for team in teams):
                raise ValidationError(_("All WhatsApp teams must belong to the number company."))

    @api.constrains("attachment_limit_mb")
    def _check_attachment_global_cap(self):
        global_cap = max(1, self.env["ir.config_parameter"].sudo().get_int(
            "flousflow_whatsapp.attachment_global_cap_mb", 10
        ))
        for number in self:
            if number.attachment_limit_mb > global_cap:
                raise ValidationError(
                    _("The attachment limit cannot exceed the global cap of %s MB.", global_cap)
                )

    def user_can_access(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        if user.has_group("flousflow_whatsapp.group_whatsapp_admin"):
            return self.company_id in user.company_ids
        if self.company_id not in user.company_ids or user in self.denied_user_ids:
            return False
        if user in self.allowed_user_ids:
            return True
        teams = self.primary_team_id | self.allowed_team_ids
        return user in teams.member_ids or user in teams.supervisor_ids


class FlousflowWhatsappNumberMember(models.Model):
    _name = "flousflow.whatsapp.number.member"
    _description = "Flous Flow WhatsApp Number User Rule"
    _order = "number_id, user_id, id"
    _check_company_auto = True

    number_id = fields.Many2one(
        "flousflow.whatsapp.number",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="number_id.company_id",
        store=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        check_company=True,
        domain="[('share', '=', False)]",
    )
    access_mode = fields.Selection(
        [("allow", "Allow"), ("deny", "Deny")],
        required=True,
        default="allow",
    )
    active = fields.Boolean(default=True)

    _number_user_unique = models.Constraint(
        "UNIQUE(number_id, user_id)",
        "A user can have only one direct rule per WhatsApp number.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.number_id._sync_direct_users()
        return records

    def write(self, values):
        numbers = self.number_id
        result = super().write(values)
        (numbers | self.number_id)._sync_direct_users()
        return result

    def unlink(self):
        numbers = self.number_id
        result = super().unlink()
        numbers._sync_direct_users()
        return result
