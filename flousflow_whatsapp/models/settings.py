from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    whatsapp_connector_url = fields.Char(
        string="WhatsApp Connector URL",
        config_parameter="flousflow_whatsapp.connector_url",
        default="http://127.0.0.1:3100",
    )
    whatsapp_attachment_global_cap_mb = fields.Integer(
        string="WhatsApp Global Attachment Cap (MB)",
        config_parameter="flousflow_whatsapp.attachment_global_cap_mb",
        default=10,
    )
