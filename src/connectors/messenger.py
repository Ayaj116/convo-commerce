"""
Facebook Messenger connector (Graph Send API).

Handles webhook verification, event parsing (PSID + text), and message
sending. Messenger's standard messaging also has a 24h window plus message
tags for specific out-of-window use cases (e.g. POST_PURCHASE_UPDATE for
order/shipping notifications).
"""
from __future__ import annotations

import datetime as dt
import logging

from config import settings
from src.connectors.base import verify_signature
from src.db.models import Channel
from src.tools import tools

log = logging.getLogger("messenger")

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class MessengerConnector:
    channel = Channel.MESSENGER

    def __init__(self) -> None:
        self.cfg = settings.messenger
        self.base = f"https://graph.facebook.com/{self.cfg.graph_version}/me/messages"

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        if mode == "subscribe" and token == self.cfg.verify_token:
            return challenge
        return None

    def verify_signature(self, payload: bytes, header_sig: str | None) -> bool:
        return verify_signature(self.cfg.app_secret, payload, header_sig)

    def parse_events(self, body: dict) -> list[dict]:
        events: list[dict] = []
        for entry in body.get("entry", []):
            for evt in entry.get("messaging", []):
                msg = evt.get("message", {})
                if not msg.get("text") or msg.get("is_echo"):
                    continue
                events.append({
                    "channel": self.channel,
                    "sender_id": evt["sender"]["id"],
                    "text": msg["text"],
                    "name": None,
                })
        return events

    def within_service_window(self, sender_id: str) -> bool:
        last = tools.last_inbound_time(f"{self.channel}:{sender_id}")
        if not last:
            return False
        try:
            ts = dt.datetime.fromisoformat(last)
        except ValueError:
            return False
        return (dt.datetime.utcnow() - ts) < dt.timedelta(hours=24)

    def send_text(self, recipient_id: str, text: str, tag: str | None = None) -> dict:
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "MESSAGE_TAG" if tag else "RESPONSE",
            "message": {"text": text},
        }
        if tag:
            payload["tag"] = tag  # e.g. POST_PURCHASE_UPDATE for order notifications
        elif not self.within_service_window(recipient_id):
            log.warning("Outside 24h window for %s — use a message tag.", recipient_id)
            return {"skipped": "outside_24h_window", "hint": "use_message_tag"}
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        if requests is None or not self.cfg.page_access_token:
            log.info("[dry-run] Messenger -> %s", payload)
            return {"dry_run": True, "payload": payload}
        params = {"access_token": self.cfg.page_access_token}
        r = requests.post(self.base, params=params, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()
