"""
Instagram Messaging connector (Meta Graph API).

Instagram DMs for an Instagram Professional account linked to a Facebook Page.
Mechanically close to Messenger — same Graph `me/messages` Send API, same
X-Hub-Signature-256 HMAC webhook signing, same verification handshake — but the
webhook payload arrives with `object: "instagram"` and the sender id is an
Instagram-scoped id (IGSID) rather than a Messenger PSID.

Instagram messaging has a 24-hour standard window like Messenger; the
HUMAN_AGENT tag can extend responses to 7 days when the app has the feature.
"""
from __future__ import annotations

import datetime as dt
import logging

from config import settings
from src.connectors.base import verify_signature
from src.db.models import Channel
from src.tools import tools

log = logging.getLogger("instagram")

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class InstagramConnector:
    channel = Channel.INSTAGRAM

    def __init__(self) -> None:
        self.cfg = settings.instagram
        self.base = f"https://graph.facebook.com/{self.cfg.graph_version}/me/messages"

    # -- webhook -----------------------------------------------------------
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
                # Skip echoes (messages the business itself sent) and non-text.
                if not msg.get("text") or msg.get("is_echo"):
                    continue
                events.append({
                    "channel": self.channel,
                    "sender_id": evt["sender"]["id"],   # IGSID
                    "text": msg["text"],
                    "name": None,
                    "platform_message_id": msg.get("mid"),
                })
        return events

    # -- window ------------------------------------------------------------
    def within_service_window(self, sender_id: str) -> bool:
        last = tools.last_inbound_time_for_profile(self.channel, sender_id)
        if not last:
            return False
        try:
            ts = dt.datetime.fromisoformat(last)
        except ValueError:
            return False
        return (dt.datetime.utcnow() - ts) < dt.timedelta(hours=24)

    # -- sending -----------------------------------------------------------
    def send_text(self, recipient_id: str, text: str, tag: str | None = None) -> dict:
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": "MESSAGE_TAG" if tag else "RESPONSE",
            "message": {"text": text},
        }
        if tag:
            payload["tag"] = tag  # e.g. HUMAN_AGENT for extended-window replies
        elif not self.within_service_window(recipient_id):
            log.warning("Outside 24h window for %s — use a message tag.", recipient_id)
            return {"skipped": "outside_24h_window", "hint": "use_message_tag"}
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        if requests is None or not self.cfg.page_access_token:
            log.info("[dry-run] Instagram -> %s", payload)
            return {"dry_run": True, "payload": payload}
        params = {"access_token": self.cfg.page_access_token}
        r = requests.post(self.base, params=params, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()
