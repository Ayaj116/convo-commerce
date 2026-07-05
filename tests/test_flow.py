"""
Lightweight tests (no external deps). Run:  python tests/test_flow.py
Uses an isolated temp DB and the mock provider.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["AI_PROVIDER"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.database import init_db  # noqa: E402
from src.db.models import Channel, OrderStatus  # noqa: E402
from src.tools import tools  # noqa: E402
from src.agent.conversation import ConversationAgent  # noqa: E402


def setup():
    init_db()
    from src.db import database as db
    db.execute("INSERT INTO products (name, category, description, price, stock_quantity) "
               "VALUES (?,?,?,?,?)", ("Aurora Runner Sneakers", "Footwear", "runners", 79.99, 10))


def test_user_find_or_create():
    u = tools.ensure_user(phone_number="19998887777", name="Test")
    assert u["user_id"]
    again = tools.get_user_by_phone_or_profile_id(phone_number="19998887777")
    assert again["user_id"] == u["user_id"]
    print("ok: user find-or-create")


def test_search():
    res = tools.get_products_by_category_or_search(query="runner")
    assert any("Runner" in p["name"] for p in res)
    print("ok: catalog search")


def test_order_and_stock():
    u = tools.ensure_user(phone_number="12223334444")
    p = tools.get_products_by_category_or_search(query="runner")[0]
    before = p["stock_quantity"]
    order = tools.create_order(u["user_id"], p["product_id"], 3)
    assert order["status"] == OrderStatus.PENDING_PAYMENT
    assert order["total_amount"] == round(p["price"] * 3, 2)
    after = tools.get_product(p["product_id"])["stock_quantity"]
    assert after == before - 3, "stock must be reserved"
    # Oversell is rejected.
    bad = tools.create_order(u["user_id"], p["product_id"], 9999)
    assert bad.get("error") == "insufficient_stock"
    print("ok: order placement + stock reservation + oversell guard")


def test_status_lifecycle():
    u = tools.ensure_user(phone_number="15556667777")
    p = tools.get_products_by_category_or_search(query="runner")[0]
    order = tools.create_order(u["user_id"], p["product_id"], 1)
    paid = tools.record_payment(order["order_id"], "PAY-123")
    assert paid["status"] == OrderStatus.PAID
    shipped = tools.update_order_status(order["order_id"], OrderStatus.SHIPPED)
    assert shipped["status"] == OrderStatus.SHIPPED
    assert tools.update_order_status(order["order_id"], "NONSENSE").get("error")
    print("ok: status lifecycle + validation")


def test_full_conversation():
    agent = ConversationAgent()
    wa = "17778889999"
    agent.handle_message(Channel.WHATSAPP, wa, "hi")
    agent.handle_message(Channel.WHATSAPP, wa, "I want running shoes")
    reply = agent.handle_message(Channel.WHATSAPP, wa,
                                 "I'll take 1 Aurora Runner Sneakers, ship to 5 Oak Ave")
    assert "order" in reply.lower() and "pay" in reply.lower()
    user = tools.get_user_by_phone_or_profile_id(phone_number=wa)
    assert tools.get_orders_for_user(user["user_id"]), "an order should exist"
    print("ok: full conversation discovery->order->payment")


if __name__ == "__main__":
    setup()
    test_user_find_or_create()
    test_search()
    test_order_and_stock()
    test_status_lifecycle()
    test_full_conversation()
    print("\nAll tests passed ✅")
