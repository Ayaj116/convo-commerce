"""
Twilio WhatsApp connector (3rd-party, 30-day trial).

An alternative delivery path for the WhatsApp channel that needs no Meta app
review — you get a working number in minutes via the Twilio WhatsApp Sandbox
during the trial. Selected with WHATSAPP_PROVIDER=twilio.

Differences from the Meta Cloud API connector:
  * Inbound webhooks are **form-encoded** (application/x-www-form-urlencoded),
    not JSON — Twilio POSTs fields like From, Body, MessageSid, ProfileName.
  * Authenticity is verified with Twilio's `X-Twilio-Signature` (HMAC-SHA1 over
    the URL + sorted POST params, keyed by the auth token), not Meta's HMAC.
  * Sending uses the Twilio REST API (messages.create) with a 'whatsapp:+E164'
    from/to. There is no 24-hour-window free-form block on the Twilio side the
    way the Cloud API enforces it (Twilio/Meta still apply session rules, but
    the connector doesn't gate on them here).

The gateway normalises the channel to 'whatsapp' regardless of provider, so the
agent, tools and notifications are provider-agnostic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from urllib.parse import parse_qs

from config import settings
from src.db.models import Channel

log = logging.getLogger("twilio_whatsapp")

try:
    from twilio.rest import Client as _TwilioClient
except ImportError:  # pragma: no cover — optional until you install twilio
    _TwilioClient = None


def _strip_wa(addr: str) -> str:
    """'whatsapp:+14155551234' -> '+14155551234' (our stored platform_user_id)."""
    return addr.split(":", 1)[1] if ":" in addr else addr


class TwilioWhatsAppConnector:
    channel = Channel.WHATSAPP
    provider = "twilio"

    def __init__(self) -> None:
        self.cfg = settings.twilio
        self._client = None
        if _TwilioClient and self.cfg.account_sid and self.cfg.auth_token:
            self._client = _TwilioClient(self.cfg.account_sid, self.cfg.auth_token)

    # -- webhook -----------------------------------------------------------
    def verify_signature(self, url: str, form: dict[str, str], header_sig: str | None) -> bool:
        """Validate Twilio's X-Twilio-Signature: base64(HMAC-SHA1(url + sorted
        concatenated params, auth_token)). If no auth token is configured we
        accept (dev/dry-run) and warn."""
        if not self.cfg.auth_token:
            log.warning("TWILIO_AUTH_TOKEN not set — accepting webhook unverified")
            return True
        if not header_sig:
            return False
        payload = url + "".join(f"{k}{form[k]}" for k in sorted(form))
        digest = hmac.new(self.cfg.auth_token.encode(), payload.encode(), hashlib.sha1).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, header_sig)

    def parse_form(self, raw_body: bytes) -> list[dict]:
        """Flatten a Twilio inbound WhatsApp POST (form-encoded) into events."""
        fields = {k: v[0] for k, v in parse_qs(raw_body.decode("utf-8")).items()}
        return self.parse_events(fields)

    def parse_events(self, fields: dict) -> list[dict]:
        body = fields.get("Body")
        sender = fields.get("From")
        if not body or not sender:
            return []
        return [{
            "channel": self.channel,
            "sender_id": _strip_wa(sender),
            "text": body,
            "name": fields.get("ProfileName"),
            "platform_message_id": fields.get("MessageSid"),
        }]

    # -- sending -----------------------------------------------------------
    def within_service_window(self, sender_id: str) -> bool:
        # Twilio manages session/template rules server-side; don't gate here.
        return True

    def send_text(self, recipient_id: str, text: str) -> dict:
        to = recipient_id if recipient_id.startswith("whatsapp:") else f"whatsapp:{recipient_id}"
        if self._client is None:
            log.info("[dry-run] Twilio WhatsApp -> %s: %s", to, text)
            return {"dry_run": True, "to": to, "body": text}
        msg = self._client.messages.create(from_=self.cfg.whatsapp_from, to=to, body=text)
        return {"sid": msg.sid, "status": msg.status, "to": to}
