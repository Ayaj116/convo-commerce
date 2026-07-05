"""
Event-driven notifications.

When an order's status changes (via update_order_status), publish an event.
Subscribers (here: the channel notifier) react by messaging the customer with
a tracking update — respecting each channel's out-of-window rules.

In production, swap the in-process bus for SNS/PubSub/Kafka; the interface
stays the same.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable

from src.db.models import Channel, OrderStatus
from src.tools import tools

log = logging.getLogger("events")

_subscribers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)


def subscribe(event: str, handler: Callable[[dict], None]) -> None:
    _subscribers[event].append(handler)


def publish(event: str, payload: dict) -> None:
    for handler in _subscribers.get(event, []):
        try:
            handler(payload)
        except Exception:  # noqa: BLE001
            log.exception("subscriber for %s failed", event)


def advance_and_notify(order_id: int, status: str, note: str | None = None) -> dict:
    """Update status AND emit an event that triggers a customer notification."""
    order = tools.update_order_status(order_id, status, note)
    if isinstance(order, dict) and order.get("order_id"):
        publish("order.status_changed", {"order": order, "status": status})
    return order


def _notify_customer(payload: dict) -> None:
    """Default subscriber: send a friendly status update over the right channel."""
    from src.connectors.whatsapp import WhatsAppConnector
    from src.connectors.messenger import MessengerConnector

    order = payload["order"]
    user = _resolve_user(order["user_id"])
    if not user:
        return

    label = OrderStatus.LABELS.get(payload["status"], payload["status"].lower())
    text = (f"Update on order #{order['order_id']}: your "
            f"{order['product']['name']} is now {label}. "
            + (f"Tracking: {order['tracking_number']}. " if order.get("tracking_number") else "")
            + "Thanks for shopping with us! 🛍️")

    if user.get("phone_number"):
        WhatsAppConnector().send_text(user["phone_number"], text)
    elif user.get("messenger_id"):
        # Order updates qualify for the POST_PURCHASE_UPDATE tag out of window.
        MessengerConnector().send_text(user["messenger_id"], text,
                                       tag="POST_PURCHASE_UPDATE")


def _resolve_user(user_id: int) -> dict | None:
    from src.db import database as db
    return db.query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))


# Register the default subscriber on import.
subscribe("order.status_changed", _notify_customer)
