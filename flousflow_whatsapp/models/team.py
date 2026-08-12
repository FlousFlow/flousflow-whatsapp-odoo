from odoo import fields, models


class FlousflowWhatsappTeam(models.Model):
    _name = "flousflow.whatsapp.team"
    _description = "Flous Flow WhatsApp Team"
    _order = "company_id, name, id"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
    )
    supervisor_ids = fields.Many2many(
        "res.users",
        "flousflow_whatsapp_team_supervisor_rel",
        "team_id",
        "user_id",
        string="Supervisors",
        domain="[('share', '=', False)]",
        check_company=True,
    )
    member_ids = fields.Many2many(
        "res.users",
        "flousflow_whatsapp_team_member_rel",
        "team_id",
        "user_id",
        string="Members",
        domain="[('share', '=', False)]",
        check_company=True,
    )
    work_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Working Hours",
        check_company=True,
        domain="[('company_id', 'in', [company_id, False])]",
    )
    active = fields.Boolean(default=True)

    _name_company_unique = models.Constraint(
        "UNIQUE(company_id, name)",
        "The WhatsApp team name must be unique per company.",
    )
