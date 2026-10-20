# Connector compatibility

| Odoo addon | Connector | Odoo | Node.js |
|---|---|---|---|
| 20.0.1.0.0 | 1.4.x | 20.0 Community or Enterprise | 22 LTS |
| 19.0.1.6.5 | 1.4.x | 19.0 Community or Enterprise | 22 LTS |
| 19.0.1.6.4 | 1.4.x | 19.0 Community or Enterprise | 22 LTS |
| 19.0.1.6.3 | 1.4.x | 19.0 Community or Enterprise | 22 LTS |
| 19.0.1.6.2 | 1.4.x | 19.0 Community or Enterprise | 22 LTS |

The Odoo 20 addon requires the Python version supported by Odoo 20 (Python
3.12 or newer). The connector remains a separate Node.js 22 LTS service.

The connector is a separately deployed runtime and is not included inside the
Odoo Apps ZIP. Both sides authenticate every HTTP call using the same strong
`FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET`.

Persist the connector `data`, `sessions` and `queue` volumes, terminate HTTPS at
a reverse proxy, restrict connector routes at the network layer where practical,
and deploy tested releases. Do not auto-upgrade dependencies on a live connector.

The connector uses Baileys and QR-paired WhatsApp Web. It is not the official
Meta WhatsApp Cloud API.
