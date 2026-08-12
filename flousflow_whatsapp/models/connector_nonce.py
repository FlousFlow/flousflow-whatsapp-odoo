from datetime import timedelta

from odoo import api, fields, models


class FlousflowWhatsappConnectorNonce(models.Model):
    _name = "flousflow.whatsapp.connector.nonce"
    _description = "Flous Flow WhatsApp Connector Nonce"
    _order = "expires_at desc, id desc"

    nonce = fields.Char(required=True, index=True, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)

    _nonce_unique = models.Constraint(
        "UNIQUE(nonce)", "This connector request nonce was already consumed."
    )

    @api.model
    def consume(self, nonce, now=None, ttl_seconds=600):
        now = now or fields.Datetime.now()
        self.env.cr.execute(
            "INSERT INTO flousflow_whatsapp_connector_nonce "
            "(nonce, expires_at, create_uid, create_date, write_uid, write_date) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (nonce) DO NOTHING RETURNING id",
            [
                nonce,
                now + timedelta(seconds=ttl_seconds),
                self.env.uid,
                now,
                self.env.uid,
                now,
            ],
        )
        return bool(self.env.cr.fetchone())

    @api.model
    def cron_gc_expired(self, now=None, batch_size=10000):
        """Delete expired replay tokens without contending with inbound requests."""
        now = now or fields.Datetime.now()
        self.env.cr.execute(
            """
            WITH expired AS (
                SELECT id
                  FROM flousflow_whatsapp_connector_nonce
                 WHERE expires_at < %s
                 ORDER BY expires_at, id
                 FOR UPDATE SKIP LOCKED
                 LIMIT %s
            )
            DELETE FROM flousflow_whatsapp_connector_nonce AS nonce
             USING expired
             WHERE nonce.id = expired.id
            RETURNING nonce.id
            """,
            [now, batch_size],
        )
        deleted_count = self.env.cr.rowcount
        self.invalidate_model()
        return deleted_count
