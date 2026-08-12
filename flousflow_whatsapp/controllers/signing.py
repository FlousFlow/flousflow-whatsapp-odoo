import hashlib
import hmac
import os
import secrets
import time


SECRET_ENV = "FLOUSFLOW_WHATSAPP_CONNECTOR_SECRET"
TIMESTAMP_HEADER = "X-FlousFlow-Timestamp"
NONCE_HEADER = "X-FlousFlow-Nonce"
SIGNATURE_HEADER = "X-FlousFlow-Signature"


def sign_connector_request(raw_body):
    """Sign an Odoo-to-connector control request with the shared deployment secret."""
    secret = os.environ.get(SECRET_ENV)
    if not secret:
        raise ConnectorRequestError(503, "connector_unconfigured", "Connector authentication is not configured.")
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    canonical = b"\n".join([timestamp.encode(), nonce.encode(), raw_body])
    return {
        TIMESTAMP_HEADER: timestamp,
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(),
    }


class ConnectorRequestError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def verify_signed_request(env, raw_body, headers, max_body_bytes=1024 * 1024):
    if len(raw_body) > max_body_bytes:
        raise ConnectorRequestError(413, "body_too_large", "Request body exceeds the configured limit.")
    secret = os.environ.get(SECRET_ENV)
    if not secret:
        raise ConnectorRequestError(503, "connector_unconfigured", "Connector authentication is not configured.")
    timestamp = (headers.get(TIMESTAMP_HEADER) or "").strip()
    nonce = (headers.get(NONCE_HEADER) or "").strip()
    signature = (headers.get(SIGNATURE_HEADER) or "").strip().lower()
    if not timestamp or not nonce or not signature:
        raise ConnectorRequestError(401, "missing_signature", "Signed connector headers are required.")
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise ConnectorRequestError(401, "invalid_timestamp", "Connector timestamp is invalid.") from exc
    now_epoch = int(time.time())
    if abs(now_epoch - request_time) > 300:
        raise ConnectorRequestError(401, "stale_request", "Connector timestamp is outside the allowed window.")
    if len(nonce) < 16 or len(nonce) > 128:
        raise ConnectorRequestError(401, "invalid_nonce", "Connector nonce is invalid.")
    canonical = b"\n".join([timestamp.encode(), nonce.encode(), raw_body])
    expected = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ConnectorRequestError(401, "invalid_signature", "Connector signature is invalid.")
    if not env["flousflow.whatsapp.connector.nonce"].sudo().consume(nonce):
        raise ConnectorRequestError(409, "replayed_request", "Connector nonce was already consumed.")
    return True
