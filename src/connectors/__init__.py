"""
Connector factory — one place that maps a channel to its connector.

Keeps the WhatsApp provider choice (Twilio vs Meta Cloud API) and the set of
supported channels in a single spot, so the gateway and the notification bus
both route outbound messages the same way.
"""
from __future__ import annotations

from functools import lru_cache

from config import settings
from src.db.models import Channel


@lru_cache(maxsize=None)
def get_connector(channel: str):
    """Return a cached connector instance for a channel.

    For WhatsApp the delivery path is chosen by WHATSAPP_PROVIDER
    ('twilio' -> Twilio, else Meta Cloud API)."""
    if channel == Channel.WHATSAPP:
        if settings.whatsapp.provider == "twilio":
            from src.connectors.twilio_whatsapp import TwilioWhatsAppConnector
            return TwilioWhatsAppConnector()
        from src.connectors.whatsapp import WhatsAppConnector
        return WhatsAppConnector()
    if channel == Channel.MESSENGER:
        from src.connectors.messenger import MessengerConnector
        return MessengerConnector()
    if channel == Channel.INSTAGRAM:
        from src.connectors.instagram import InstagramConnector
        return InstagramConnector()
    if channel == Channel.TELEGRAM:
        from src.connectors.telegram import TelegramConnector
        return TelegramConnector()
    raise ValueError(f"unsupported channel: {channel}")


def send_on_channel(channel: str, recipient_id: str, text: str, tag: str | None = None) -> dict:
    """Deliver a text message on the given channel to the right recipient id.

    `tag` (Messenger/Instagram message tag, e.g. POST_PURCHASE_UPDATE) is passed
    through when the connector supports it — used for out-of-window order updates.
    """
    connector = get_connector(channel)
    try:
        return connector.send_text(recipient_id, text, tag=tag)  # type: ignore[call-arg]
    except TypeError:
        # Connectors without a tag param (WhatsApp/Telegram/Twilio).
        return connector.send_text(recipient_id, text)
