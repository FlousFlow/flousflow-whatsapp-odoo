# Changelog

## 19.0.1.6.5 - 2026-08-13

- Open Inbox through its native Odoo client action so WhatsApp becomes the
  current app and its Reporting and Configuration menus remain visible.

## 19.0.1.6.4 - 2026-08-13

- Add a WhatsApp Configuration > Settings menu that opens this app directly.
- Give the settings app stable Odoo 19 identifiers for reliable rendering.

## 19.0.1.6.3 - 2026-08-13

- Improve Odoo Apps installation-command contrast across store themes.
- Replace a non-ASCII dash with an HTML entity to avoid mojibake.

## 19.0.1.6.2 - 2026-08-12

- Dynamically provision every new self-hosted connector session from Odoo.
- Remove the normal need to edit `WHATSAPP_SESSION_KEYS` or restart Docker.

## 19.0.1.6.1 - 2026-08-12

- Force the Inbox menu entry out of stale debug bundles before opening the client action.
- Prevent long-lived caching of stable Odoo debug asset URLs in the deployment guide.

## 19.0.1.6.0 - 2026-08-12

- Add self-hosted connector controls and automatic globally unique session keys.
- Allow administrators to connect, display QR and disconnect directly from Odoo.

## 19.0.1.5.0 - 2026-08-12

- Add administrator-only, number-scoped cleanup for incorrectly paired accounts.
- Delete only unused contacts proven to have been created by this module for that number.
- Preserve contacts used by CRM, Sales, Accounting, users, or child contacts.
- Disable inbound and outbound synchronization after cleanup until pairing is verified.
- Add an immutable audit event and exact typed confirmation for every cleanup.

## 19.0.1.4.0 - 2026-08-12

- Send browser recordings as native WhatsApp push-to-talk voice notes.
- Preserve uploaded audio as ordinary audio and inbound PTT metadata.
- Enforce a configurable customer-service window with audited supervisor override.
- Add connector version, heartbeat and durable queue monitoring.
- Add failed-message reporting and supervisor manual retry.
- Harden connector delivery with serialized, configurable outbound pacing.
- Clarify unofficial QR connector requirements and legal limitations.

## 19.0.1.3.0

- Add durable connector event replay, delivery/read receipts and typing events.
- Add bounded retry handling and readiness probing.
