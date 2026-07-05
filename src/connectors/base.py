"""Base connector: shared HMAC signature verification + interface."""
from __future__ import annotations

import hashlib
import hmac
from typing import Protocol


def verify_signature(app_secret: str | None, payload: bytes, header_sig: str | None) -> bool:
    """Validate Meta's X-Hub-Signature-256 header (sha256=...)."""
    if not app_secret or not header_sig:
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header_sig)


class Connector(Protocol):
    channel: str

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None: ...
    def parse_events(self, body: dict) -> list[dict]: ...
    def send_text(self, recipient_id: str, text: str) -> dict: ...
