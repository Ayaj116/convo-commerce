"""
Live integration tests against Supabase (schema `commerce`).

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY (see .env) — skips cleanly if
unset, so this still works out of the box for casual contributors. When the
key IS present, every test creates its own uniquely-suffixed customer/product
fixtures (never assumes a clean table) and best-effort tears them down at the
end, so repeated runs don't pile up rows in the live, shared project.

Run:  python tests/test_flow.py
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("AI_PROVIDER", "mock")

from config import settings  # noqa: E402

if not settings.supabase.service_key:
    print("SUPABASE_SERVICE_KEY not set — skipping live integration tests.")
    sys.exit(0)

from src.db import database as db  # noqa: E402
from src.db.models import Channel, OrderStatus  # noqa: E402
from src.tools import tools  # noqa: E402
from src.agent.conversation import ConversationAgent  # noqa: E402

_created_customers: list[str] = []
_created_products: list[str] = []


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _new_whatsapp_number() -> str:
    return "1" + uuid.uuid4().hex[:9]


def _seed_test_product(stock: int = 10) -> dict:
    # No hyphen in the name — the mock provider's naive text-extraction
    # sanitizer turns punctuation into spaces when building a search query,
    # which would otherwise break the ILIKE substring match.
    product = db.insert_one("products", {
        "name": f"Test Sneaker {uuid.uuid4().hex[:8]}",
        "sku": _unique("TST"),
        "category": "Footwear",
        "description": "test fixture",
        "price": 79.99,
        "stock_quantity": stock,
        "is_active": True,
    })
    _created_products.append(product["id"])
    return product


def _try(fn, *args) -> None:
    try:
        fn(*args)
    except db.DatabaseError:
        pass


def _cleanup_customer(customer_id: str) -> None:
    """Best-effort teardown in FK-safe order (orders -> profiles -> customer)."""
    for order in db.select("orders", {"customer_id": db.eq(customer_id)}):
        oid = order["id"]
        for payment in db.select("payments", {"order_id": db.eq(oid)}):
            _try(db.delete, "payment_transactions", {"payment_id": db.eq(payment["id"])})
        _try(db.delete, "payments", {"order_id": db.eq(oid)})
        _try(db.delete, "invoices", {"order_id": db.eq(oid)})
        _try(db.delete, "order_status_history", {"order_id": db.eq(oid)})
        _try(db.delete, "order_items", {"order_id": db.eq(oid)})
        _try(db.delete, "orders", {"id": db.eq(oid)})
    for profile in db.select("customer_profiles", {"customer_id": db.eq(customer_id)}):
        for convo in db.select("conversations", {"profile_id": db.eq(profile["id"])}):
            _try(db.delete, "messages", {"conversation_id": db.eq(convo["id"])})
            _try(db.delete, "conversations", {"id": db.eq(convo["id"])})
        _try(db.delete, "customer_profiles", {"id": db.eq(profile["id"])})
    _try(db.delete, "customers", {"id": db.eq(customer_id)})


def teardown() -> None:
    for customer_id in _created_customers:
        _cleanup_customer(customer_id)
    for product_id in _created_products:
        _try(db.delete, "products", {"id": db.eq(product_id)})


def test_user_find_or_create():
    phone = _new_whatsapp_number()
    profile = tools.ensure_customer_profile(Channel.WHATSAPP, phone, display_name="Test", phone_number=phone)
    _created_customers.append(profile["customer_id"])
    again = tools.get_user_by_phone_or_profile_id(phone_number=phone)
    assert again["customer_id"] == profile["customer_id"]
    print("ok: customer find-or-create")


def test_search():
    product = _seed_test_product()
    res = tools.get_products_by_category_or_search(query=product["name"])
    assert any(p["id"] == product["id"] for p in res)
    print("ok: catalog search")


def test_order_and_stock():
    phone = _new_whatsapp_number()
    profile = tools.ensure_customer_profile(Channel.WHATSAPP, phone, phone_number=phone)
    _created_customers.append(profile["customer_id"])
    product = _seed_test_product(stock=5)

    order = tools.create_order(profile["customer_id"], [{"product_id": product["id"], "quantity": 3}])
    assert order["status"] == OrderStatus.CREATED
    assert order["total"] == round(product["price"] * 3, 2)

    after = tools.get_product(product["id"])
    assert after["stock_quantity"] == 5 - 3, "stock must be decremented"

    bad = tools.create_order(profile["customer_id"], [{"product_id": product["id"], "quantity": 999}])
    assert bad.get("error") == "insufficient_stock"
    print("ok: order placement + stock decrement + oversell guard")


def test_status_lifecycle_and_invoice():
    phone = _new_whatsapp_number()
    profile = tools.ensure_customer_profile(Channel.WHATSAPP, phone, phone_number=phone)
    _created_customers.append(profile["customer_id"])
    product = _seed_test_product(stock=5)

    order = tools.create_order(profile["customer_id"], [{"product_id": product["id"], "quantity": 1}])
    assert tools.get_invoice(order["id"]).get("status") == "not_available"

    link = tools.create_payment_link(order["id"], "external")
    paid = tools.mark_payment_paid(link["payment_id"], "PAY-TEST-1")
    assert paid["status"] == OrderStatus.PAID

    invoice = tools.get_invoice(order["id"])
    assert invoice.get("invoice_number")

    shipped = tools.update_order_status(order["id"], OrderStatus.SHIPPED, note=tools.format_tracking_remark("TRK123"))
    assert shipped["status"] == OrderStatus.SHIPPED
    assert tools.get_latest_tracking_number(order["id"]) == "TRK123"
    assert tools.update_order_status(order["id"], "NONSENSE").get("error")
    print("ok: status lifecycle + payment + invoice + tracking + validation")


def test_full_conversation():
    product = _seed_test_product(stock=5)
    phone = _new_whatsapp_number()
    agent = ConversationAgent()
    agent.handle_message(Channel.WHATSAPP, phone, "hi")
    agent.handle_message(Channel.WHATSAPP, phone, f"I want {product['name']}")
    reply = agent.handle_message(Channel.WHATSAPP, phone,
                                 f"I'll take 1 {product['name']}, ship to 5 Oak Ave")
    profile = tools.get_user_by_phone_or_profile_id(phone_number=phone)
    _created_customers.append(profile["customer_id"])
    assert reply and "order" in reply.lower() and "pay" in reply.lower()
    assert tools.get_orders_for_customer(profile["customer_id"]), "an order should exist"
    print("ok: full conversation discovery->order->payment")


def test_duplicate_webhook_is_deduped():
    _seed_test_product(stock=5)
    phone = _new_whatsapp_number()
    agent = ConversationAgent()
    msg_id = _unique("wamid")
    first = agent.handle_message(Channel.WHATSAPP, phone, "hi", platform_message_id=msg_id)
    assert first is not None
    duplicate = agent.handle_message(Channel.WHATSAPP, phone, "hi", platform_message_id=msg_id)
    assert duplicate is None, "duplicate delivery must be skipped"
    profile = tools.get_user_by_phone_or_profile_id(phone_number=phone)
    _created_customers.append(profile["customer_id"])
    print("ok: duplicate webhook delivery is deduped")


if __name__ == "__main__":
    try:
        test_user_find_or_create()
        test_search()
        test_order_and_stock()
        test_status_lifecycle_and_invoice()
        test_full_conversation()
        test_duplicate_webhook_is_deduped()
        print("\nAll tests passed.")
    finally:
        teardown()
