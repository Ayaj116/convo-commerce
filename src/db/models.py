"""Typed domain models and status constants (lightweight, dict-friendly)."""
from __future__ import annotations

from dataclasses import dataclass, asdict


class OrderStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

    ALL = [
        PENDING_PAYMENT, PAID, PACKED, SHIPPED,
        OUT_FOR_DELIVERY, DELIVERED, CANCELLED, REFUNDED,
    ]

    # Friendly labels for customer-facing messages.
    LABELS = {
        PENDING_PAYMENT: "awaiting payment",
        PAID: "payment received",
        PACKED: "packed and ready",
        SHIPPED: "shipped",
        OUT_FOR_DELIVERY: "out for delivery",
        DELIVERED: "delivered",
        CANCELLED: "cancelled",
        REFUNDED: "refunded",
    }


class Channel:
    WHATSAPP = "whatsapp"
    MESSENGER = "messenger"


@dataclass
class User:
    user_id: int
    name: str | None
    phone_number: str | None
    messenger_id: str | None
    preferences: str = "{}"

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Product:
    product_id: int
    name: str
    category: str
    price: float
    stock_quantity: int
    currency: str = "USD"
    description: str | None = None

    def dict(self) -> dict:
        return asdict(self)
