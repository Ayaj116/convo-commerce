"""
Telegram Bot API connector.

Unlike WhatsApp/Messenger there is no Meta-style GET verification handshake —
the webhook is registered once via setWebhook() (see set_webhook() below, and
scripts/set_telegram_webhook.py), and Telegram authenticates each POST via a
secret token header instead of HMAC signing. There is also no 24-hour
messaging window: once a user has started a chat with the bot, it can
message them freely.
"""
from __future__ import annotations

import logging

from config import settings
from src.db.models import Channel

log = logging.getLogger("telegram")

try:
    import requests  # available in prod; optional locally
except ImportError:  # pragma: no cover
    requests = None


class TelegramConnector:
    channel = Channel.TELEGRAM

    def __init__(self) -> None:
        self.cfg = settings.telegram
        self.base = f"https://api.telegram.org/bot{self.cfg.bot_token}"

    # -- webhook -----------------------------------------------------------
    def verify_secret_token(self, header_value: str | None) -> bool:
        """Telegram echoes back the secret_token you set via setWebhook() as
        the X-Telegram-Bot-Api-Secret-Token header on every POST."""
        if not self.cfg.webhook_secret:
            log.warning("TELEGRAM_WEBHOOK_SECRET not set — accepting webhook calls unverified")
            return True
        return header_value == self.cfg.webhook_secret

    def parse_events(self, body: dict) -> list[dict]:
        """Flatten a Telegram update into [{sender_id, text, name, platform_message_id}]."""
        message = body.get("message") or body.get("edited_message")
        if not message or "text" not in message:
            return []
        chat_id = str(message["chat"]["id"])
        sender = message.get("from", {})
        name = sender.get("first_name") or sender.get("username")
        return [{
            "channel": self.channel,
            "sender_id": chat_id,
            "text": message["text"],
            "name": name,
            # Telegram message_ids are only unique per chat, so scope them.
            "platform_message_id": f"{chat_id}:{message['message_id']}",
        }]

    # -- sending -------------------------------------------------------------
    def within_service_window(self, sender_id: str) -> bool:
        """Telegram bots have no messaging-window restriction."""
        return True

    def send_text(self, recipient_id: str, text: str) -> dict:
        return self._post("sendMessage", {"chat_id": recipient_id, "text": text})

    def set_webhook(self, url: str) -> dict:
        """One-time setup call to register the webhook URL with Telegram."""
        payload: dict = {"url": url}
        if self.cfg.webhook_secret:
            payload["secret_token"] = self.cfg.webhook_secret
        return self._post("setWebhook", payload)

    def _post(self, method: str, payload: dict) -> dict:
        if requests is None or not self.cfg.bot_token:
            log.info("[dry-run] Telegram -> %s %s", method, payload)
            return {"dry_run": True, "payload": payload}
        r = requests.post(f"{self.base}/{method}", json=payload, timeout=15)
        if not r.ok:
            log.error("Telegram API error %s: %s", r.status_code, r.text)
            r.raise_for_status()
        return r.json()
