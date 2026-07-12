"""Typed domain models and status constants (lightweight, dict-friendly).

Mirrors the Supabase `commerce` schema (see src/db/migration_001.sql for the
handful of columns/functions layered on top of it).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


class OrderStatus:
    """Matches the commerce.orders_status_check constraint (confirmed via
    probing — PACKED/OUT_FOR_DELIVERY/REFUNDED/FAILED are all rejected)."""
    CREATED = "CREATED"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    PROCESSING = "PROCESSING"  # covers packing/preparing between PAID and SHIPPED
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

    ALL = [CREATED, PENDING_PAYMENT, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED]
    SETTABLE = ALL

    # No dedicated REFUNDED order status exists — refunds are tracked at the
    # payment level (PaymentStatus.REFUNDED); a refunded order is also marked
    # CANCELLED here so its stock gets restocked.
    RESTOCKING = {CANCELLED}

    # Friendly labels for customer-facing messages.
    LABELS = {
        CREATED: "order received",
        PENDING_PAYMENT: "awaiting payment",
        PAID: "payment received",
        PROCESSING: "being prepared",
        SHIPPED: "shipped",
        DELIVERED: "delivered",
        CANCELLED: "cancelled",
    }


class Channel:
    WHATSAPP = "whatsapp"
    MESSENGER = "messenger"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"

    ALL = [WHATSAPP, MESSENGER, INSTAGRAM, TELEGRAM]


class MessageDirection:
    """Matches the commerce.messages_direction_check constraint (uppercase only)."""
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageType:
    """Matches the commerce.messages_message_type_check constraint (uppercase
    only — confirmed values; DOCUMENT/TEMPLATE are rejected by the constraint)."""
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"


class PaymentStatus:
    """Matches the commerce.payments_status_check constraint (confirmed via
    probing — PAID/SUCCEEDED/COMPLETED/PROCESSING are all rejected; the
    'paid' state is spelled SUCCESS)."""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class InvoiceStatus:
    """Matches the commerce.invoices_status_check constraint (confirmed via
    probing — ISSUED/DRAFT/SENT/PENDING are all rejected). We only ever
    create an invoice once payment is confirmed, so PAID is the only status
    this app needs; VOID exists for a cancelled/refunded invoice."""
    PAID = "PAID"
    VOID = "VOID"


@dataclass
class Customer:
    id: str
    full_name: str
    email: str | None = None

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class CustomerProfile:
    id: str
    customer_id: str
    channel: str
    platform_user_id: str
    display_name: str | None = None
    phone_number: str | None = None

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Conversation:
    id: str
    profile_id: str
    status: str = "OPEN"

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Product:
    id: str
    name: str
    price: float
    sku: str | None = None
    description: str | None = None
    category: str | None = None
    stock_quantity: int = 0
    tax_percent: float = 0
    is_active: bool = True

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderItem:
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price: float
    tax: float = 0
    discount: float = 0
    total: float = 0

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Order:
    id: str
    order_number: str
    customer_id: str
    status: str = OrderStatus.CREATED
    currency: str = "USD"
    subtotal: float = 0
    tax: float = 0
    discount: float = 0
    total: float = 0
    delivery_address: str | None = None
    conversation_id: str | None = None

    def dict(self) -> dict:
        return asdict(self)
