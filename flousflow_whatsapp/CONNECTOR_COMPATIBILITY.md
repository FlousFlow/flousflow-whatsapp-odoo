# Connector compatibility

| Odoo addon | Connector | Odoo | Node.js |
|---|---|---|---|
| 19.0.1.6.3 | 1.4.x | 19.0 Community or Enterprise | 22 LTS |
| 19.0.1.6.2 | 1.4.x | 19.0 Community or Enterprise | 22 LTS |

The connector is a separately deployed runtime and is not included inside the
Odoo Apps ZIP. Both sides authenticate every HTTP call using the same strong
`FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET`.

Persist the connector `data`, `sessions` and `queue` volumes, terminate HTTPS at
a reverse proxy, restrict connector routes at the network layer where practical,
and deploy tested releases. Do not auto-upgrade dependencies on a live connector.

The connector uses Baileys and QR-paired WhatsApp Web. It is not the official
Meta WhatsApp Cloud API.
