"""
WhatsApp Business (Cloud API) connector.

Responsibilities:
  * Webhook verification (GET) and event parsing (POST).
  * Sending messages via the Graph API.
  * Enforcing the 24-hour customer-service window: outside it, only approved
    message templates may be sent (free-form text is blocked by Meta).
"""
from __future__ import annotations

import datetime as dt
import logging

from config import settings
from src.connectors.base import verify_signature
from src.db.models import Channel
from src.tools import tools

log = logging.getLogger("whatsapp")

try:
    import requests  # available in prod; optional locally
except ImportError:  # pragma: no cover
    requests = None


class WhatsAppConnector:
    channel = Channel.WHATSAPP

    def __init__(self) -> None:
        self.cfg = settings.whatsapp
        self.base = (f"https://graph.facebook.com/{self.cfg.graph_version}/"
                     f"{self.cfg.phone_number_id}/messages")

    # -- webhook ---------------------------------------------------------
    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        if mode == "subscribe" and token == self.cfg.verify_token:
            return challenge
        return None

    def verify_signature(self, payload: bytes, header_sig: str | None) -> bool:
        return verify_signature(self.cfg.app_secret, payload, header_sig)

    def parse_events(self, body: dict) -> list[dict]:
        """Flatten a WhatsApp webhook payload into [{sender_id, text, name}]."""
        events: list[dict] = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {c["wa_id"]: c.get("profile", {}).get("name")
                            for c in value.get("contacts", [])}
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    sender = msg["from"]
                    events.append({
                        "channel": self.channel,
                        "sender_id": sender,
                        "text": msg["text"]["body"],
                        "name": contacts.get(sender),
                        "platform_message_id": msg.get("id"),
                    })
        return events

    # -- 24-hour window --------------------------------------------------
    def within_service_window(self, sender_id: str) -> bool:
        """True if the last inbound message was < 24h ago."""
        last = tools.last_inbound_time_for_profile(self.channel, sender_id)
        if not last:
            return False
        try:
            ts = dt.datetime.fromisoformat(last)
        except ValueError:
            return False
        return (dt.datetime.utcnow() - ts) < dt.timedelta(hours=24)

    # -- sending ---------------------------------------------------------
    def send_text(self, recipient_id: str, text: str) -> dict:
        if not self.within_service_window(recipient_id):
            log.warning("Outside 24h window for %s — free-form text blocked; "
                        "use a template.", recipient_id)
            return {"skipped": "outside_24h_window",
                    "hint": "send_template", "recipient": recipient_id}
        return self._post({
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "text",
            "text": {"body": text},
        })

    def send_template(self, recipient_id: str, template: str, lang: str = "en_US",
                      components: list | None = None) -> dict:
        """Approved template — the only thing allowed outside the 24h window."""
        return self._post({
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "template",
            "template": {"name": template, "language": {"code": lang},
                         "components": components or []},
        })

    def _post(self, payload: dict) -> dict:
        if requests is None or not self.cfg.access_token or not self.cfg.phone_number_id:
            log.info("[dry-run] WhatsApp -> %s", payload)
            return {"dry_run": True, "payload": payload}
        headers = {"Authorization": f"Bearer {self.cfg.access_token}",
                   "Content-Type": "application/json"}
        r = requests.post(self.base, json=payload, headers=headers, timeout=15)
        if not r.ok:
            log.error("WhatsApp API error %s: %s", r.status_code, r.text)
            r.raise_for_status()
        return r.json()
