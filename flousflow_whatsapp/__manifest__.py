{
    "name": "WhatsApp Shared Inbox",
    "version": "20.0.1.0.0",
    "category": "Sales/CRM",
    "summary": "Presence-aware shared WhatsApp inbox with CRM, Sales and Accounting bridges",
    "description": """
Flous Flow WhatsApp is a self-contained Odoo 20 Community suite.

Manage shared WhatsApp numbers, team access, conversations, routing, SLA,
CRM handoff, HR operational availability, quotation delivery and customer
statements, all from one module.

Highlights:
- HMAC-signed connector webhooks (timestamp window + nonce replay protection)
- Media policy validated on real file signatures (blocks disguised video)
- Row-level conversation locks with lease/heartbeat and advisory locks
- Multi-company safe security with Odoo 20 access controls and scoped domains
- Idempotent inbound/outbound message handling
- Send quotations and customer statements as PDFs from the inbox
""",
    "author": "Flous Flow",
    "website": "https://flousflow.com",
    "support": "support@flousflow.com",
    "license": "LGPL-3",
    "icon": "flousflow_whatsapp/static/description/icon.png",
    "images": [
        "static/description/images/cover_screenshot.png",
        "static/description/images/inbox.png",
        "static/description/images/numbers.png",
        "static/description/images/number_form.png",
    ],
    "depends": ["base", "mail", "bus", "contacts", "crm", "hr", "sale", "account", "web"],
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "reports/statement_report.xml",
        "views/whatsapp_views.xml",
        "views/wizard_views.xml",
        "views/inherited_views.xml",
        "views/settings_views.xml",
        "views/sale_order_views.xml",
        "views/sale_document_wizard_views.xml",
        "views/sale_order_send_wizard_views.xml",
        "views/statement_document_wizard_views.xml",
        "views/statement_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "assets": {
        "web.assets_backend": [
            "flousflow_whatsapp/static/src/qr/auto_refresh_qr.js",
            "flousflow_whatsapp/static/src/qr/auto_refresh_qr.xml",
            "flousflow_whatsapp/static/src/inbox/inbox_service.js",
            "flousflow_whatsapp/static/src/inbox/phone_format.js",
            "flousflow_whatsapp/static/src/inbox/audio.js",
            "flousflow_whatsapp/static/src/inbox/inbox.js",
            "flousflow_whatsapp/static/src/inbox/inbox.xml",
            "flousflow_whatsapp/static/src/inbox/inbox.scss",
        ],
        "web.assets_unit_tests": [
            "flousflow_whatsapp/static/tests/inbox.test.js",
        ],
    },
}
