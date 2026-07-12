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


def advance_and_notify(order_id: str, status: str, note: str | None = None) -> dict:
    """Update status AND emit an event that triggers a customer notification."""
    order = tools.update_order_status(order_id, status, note)
    if isinstance(order, dict) and order.get("id"):
        publish("order.status_changed", {"order": order, "status": status})
    return order


def _recipient_id(profile: dict) -> str:
    """WhatsApp addresses by phone number; every other channel by platform id."""
    if profile["channel"] == Channel.WHATSAPP and profile.get("phone_number"):
        return profile["phone_number"]
    return profile["platform_user_id"]


def _build_message(order: dict, status: str) -> str:
    item_names = [item["product"]["name"] for item in order.get("items", []) if item.get("product")]
    items_text = ", ".join(item_names) if item_names else f"order {order['order_number']}"
    verb = "is" if len(item_names) <= 1 else "are"

    # A payment confirmation is the moment the customer most wants detail: confirm
    # the charge in real time, restate the promised delivery ETA and the invoice.
    if status == OrderStatus.PAID:
        eta = tools.estimate_eta(order_id=order["id"])
        invoice = tools.get_invoice(order["id"])
        parts = [f"Payment received for order #{order['order_number']} — you're all set! \U0001f389",
                 f"We're preparing your {items_text}."]
        if isinstance(eta, dict) and eta.get("available"):
            parts.append(f"Estimated delivery by {_fmt_eta(eta['promised_by'])}.")
        if isinstance(invoice, dict) and invoice.get("invoice_number"):
            parts.append(f"Invoice {invoice['invoice_number']} is attached to your order.")
        return " ".join(parts)

    label = OrderStatus.LABELS.get(status, status.lower())
    tracking = tools.get_latest_tracking_number(order["id"]) if status == OrderStatus.SHIPPED else None
    return (f"Update on order #{order['order_number']}: your {items_text} {verb} now {label}. "
            + (f"Tracking: {tracking}. " if tracking else "")
            + "Thanks for ordering with us! \U0001f6d2")


def _fmt_eta(iso: str) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%I:%M %p UTC").lstrip("0")
    except (ValueError, AttributeError):
        return iso


def _notify_customer(payload: dict) -> None:
    """Default subscriber: send a friendly status update over the customer's
    channel (WhatsApp/Twilio, Messenger, Instagram or Telegram)."""
    from src.connectors import send_on_channel

    order = payload["order"]
    status = payload["status"]
    profiles = tools.get_channel_profiles_for_customer(order["customer_id"])
    if not profiles:
        return

    text = _build_message(order, status)
    # Order updates qualify for the POST_PURCHASE_UPDATE tag on Meta channels
    # when outside the 24h window.
    tag_channels = {Channel.MESSENGER, Channel.INSTAGRAM}

    # Prefer the channel the customer most recently used; deliver on the first
    # reachable one (they usually have a single channel profile anyway).
    for profile in profiles:
        channel = profile["channel"]
        tag = "POST_PURCHASE_UPDATE" if channel in tag_channels else None
        try:
            send_on_channel(channel, _recipient_id(profile), text, tag=tag)
            log.info("notified customer on %s about order %s -> %s",
                     channel, order["order_number"], status)
            break
        except Exception:  # noqa: BLE001 — try the next channel
            log.exception("failed to notify on %s", channel)


# Register the default subscriber on import.
subscribe("order.status_changed", _notify_customer)
