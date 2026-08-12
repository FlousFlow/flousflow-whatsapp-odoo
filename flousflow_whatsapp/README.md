# Flous Flow WhatsApp

A self-contained **Odoo 19 Community** suite: a presence-aware shared WhatsApp
inbox with CRM, Sales and Accounting bridges, all in **one module**.

Formerly three modules (`flousflow_whatsapp_crm`, `flousflow_whatsapp_sale`,
`flousflow_whatsapp_account`), merged into a single standalone addon.

## Features

- **Shared team inbox** (OWL) with real-time bus updates and a fallback poller
- **Numbers & teams**: multi-company WhatsApp numbers, direct allow/deny rules,
  team members and supervisors, QR-pairing flow with live status
- **Routing & SLA**: least-open + round-robin assignment, online/away/busy
  awareness, first-response and reply SLAs with breach tracking
- **Conversation locking**: lease-based write locks with heartbeat, supervisor
  takeover, offline release and external-reply detection
- **CRM handoff**: create leads from conversations with safe partner resolution
  (no guessing on conflicting phone/email), advisory-locked de-duplication
- **Sales bridge**: send quotation PDFs from the inbox or the sale order form
- **Accounting bridge**: send customer/vendor statements as PDFs (self-contained
  statement engine + QWeb report — no third-party report addon required)
- **Connector API**: HMAC-SHA256 signed webhooks (timestamp window + nonce
  replay protection), outbox claiming, receipts, media policy validated on real
  file signatures (blocks disguised video)
- **Voice notes and audio**: record native push-to-talk voice notes in the Odoo
  inbox, preview them before sending, or attach ordinary audio files
- **Outbound safeguards**: configurable customer-service window, audited
  supervisor override, serialized sending and configurable pacing
- **Operations**: connector version/queue heartbeat, bounded retries,
  failed-message reporting and supervisor manual retry
- **Wrong-number recovery**: administrators can clean synchronized messages and
  conversations for one number, optionally remove only unused module-created
  contacts, and disable synchronization until pairing is verified

## Dependencies

Odoo core only: `base`, `mail`, `bus`, `contacts`, `crm`, `hr`, `sale`,
`account`, `web`.

## Installation

### Self-hosted connector

The Odoo Apps ZIP installs only the addon. Run the separately supplied Connector
Docker image on infrastructure controlled by you or the customer. Configure the
same `FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET` in both the Odoo service environment
and connector environment, and set the private Connector URL in Odoo Settings.
`WHATSAPP_SESSION_KEYS` is only an optional migration seed for sessions created
by older releases; new Odoo numbers register themselves automatically.
Administrators can then use **Connect / Show QR** and **Disconnect** from the
number form; no shell command is required for normal pairing.

Install the companion connector on the customer's Linux server:

```bash
git clone --branch v1.4.0 --depth 1 https://github.com/FlousFlow/flousflow-whatsapp-connector.git
cd flousflow-whatsapp-connector
sudo ./deploy/install.sh --odoo-url https://odoo.example.com
```

The connector is deliberately installed outside Odoo. The addon does not
download or execute external code, in accordance with Odoo Apps rules.

Copy the `flousflow_whatsapp` folder into your Odoo addons path, update the
addons path in your Odoo configuration and install the addon:

```bash
# typical local install (adapt to your environment)
odoo-bin -i flousflow_whatsapp -d <database> --stop-after-init
```

## External Connector Service

This module does **not** talk to WhatsApp directly. It exposes a signed HTTP
API that a companion QR-based connector service (`connector_url`, default
`http://127.0.0.1:3100`) calls.

The ready-to-run connector lives in its own repository:

```
https://github.com/FlousFlow/flousflow_whatsapp_connector
```

It is a Node.js / Baileys gateway that pairs numbers via QR, bridges messages,
serializes outbound traffic with a configurable minimum delay, and reports its
version and durable inbound queue depth to Odoo. The customer-service window is
enforced in Odoo with an audited supervisor override.

Set the shared secret on the Odoo server environment:

```
FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET=<strong-random-secret>
```

Without it, all connector endpoints return `503 connector_unconfigured`.

### Connector stability & WhatsApp ban avoidance

The WhatsApp connection lives in the **external connector service**, not in
this Odoo module. To avoid number bans and service interruptions the connector
**must**:

- **Keep its WhatsApp client library up to date** through tested, versioned
  connector releases. The gateway negotiates the current WhatsApp Web protocol
  version at startup, but does not auto-install dependency upgrades in production.
- **Reuse one persistent session** — do not log in repeatedly. Generate a QR
  once, persist the credentials, and reconnect on network loss.
- **Respect WhatsApp rate limits** — introduce a delay between outbound
  messages and never burst large batches from one number.
- **Respect the configured customer-service window** — Odoo blocks late replies
  by default; only supervisors can override it with an audited reason.
- **Gracefully degrade** — report `reconnect` / `error` states to this module
  through the session status endpoint instead of silently stopping, so agents
  see the number state and the module can hold outbound messages.
- **Warm up new numbers** — avoid immediately sending bulk content from a
  freshly paired number.

## Security

- `auth="public"` API routes are protected by HMAC signatures, a 5-minute
  timestamp window, and one-time nonces stored in the database.
- Media is validated by magic bytes (WebM/MP4 container inspection), not just
  the declared MIME type. Video is blocked.
- Record rules enforce multi-company isolation and per-number team access;
  audit events are immutable.
- Odoo 19 privileges: `Agent`, `Supervisor`, `Administrator`, `Executive`.

## Important WhatsApp Notice

This addon uses a companion QR-paired, unofficial WhatsApp Web connector. It is
not the Meta WhatsApp Cloud API, is not endorsed by Meta or WhatsApp, and cannot
guarantee that a number will not be restricted or disconnected. The customer is
responsible for consent, message content, privacy/marketing rules and WhatsApp's
terms. Do not use it for unsolicited bulk messaging.

## Tests

```bash
# adapt the addons path and database to your environment
odoo-bin --http-port=8071 --test-enable -i flousflow_whatsapp -d <test_db> --stop-after-init
```

Note: the `test_connector_http` HttpCase suite needs a running HTTP server and
is intended to be run with the server up (`--http-port` without
`--stop-after-init`), or it reports 404 route-not-found.

## Configuration

- `WhatsApp > Configuration > Numbers/Teams`
- `Settings > WhatsApp CRM`: connector URL, global attachment cap (MB)

## Manual Test Checklist

- [ ] Module installs without errors
- [ ] Create a number → QR state → connector reports `connected`
- [ ] Record a voice note → preview → send → verify native PTT audio
- [ ] Upload an audio file → verify ordinary audio, not a voice note
- [ ] Send a signed event → conversation created & routed to the least-busy online agent
- [ ] Two agents: only the assigned agent can reply; others see read-only
- [ ] Supervisor takeover works and is audited
- [ ] Send a quotation PDF (sale order) → message queued with document
- [ ] Generate a partner statement → PDF preview and send via WhatsApp
- [ ] Offline agent conversations reassign after the grace period
- [ ] Expired service window blocks agents; supervisor override is audited
- [ ] Failed Messages report can requeue a failed outbound message
