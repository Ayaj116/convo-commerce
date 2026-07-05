"""
Internal tool calls.

These are the *only* functions the AI is allowed to call. Each one is a small,
well-validated unit of business logic over the database. They return plain
dicts so they serialize cleanly back into any LLM's tool-result format.

Public tools (exposed to the model):
  * get_user_by_phone_or_profile_id
  * get_products_by_category_or_search
  * create_order
  * update_order_status
  * log_message
  * get_order            (tracking / aftersales lookup)
  * create_payment_link  (payment integration helper)

Also included: internal helpers used by the connectors/agent (create_user,
ensure_user) that are not surfaced to the model.
"""
from __future__ import annotations

import json
from typing import Any

from config import settings
from src.db import database as db
from src.db.models import OrderStatus


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def get_user_by_phone_or_profile_id(
    phone_number: str | None = None,
    messenger_id: str | None = None,
) -> dict | None:
    """Fetch a user by WhatsApp phone number or Messenger profile id."""
    if phone_number:
        return db.query_one(
            "SELECT * FROM users WHERE phone_number = ?", (phone_number,)
        )
    if messenger_id:
        return db.query_one(
            "SELECT * FROM users WHERE messenger_id = ?", (messenger_id,)
        )
    return None


def create_user(
    name: str | None = None,
    phone_number: str | None = None,
    messenger_id: str | None = None,
    preferences: dict | None = None,
) -> dict:
    uid = db.execute(
        "INSERT INTO users (name, phone_number, messenger_id, preferences) VALUES (?, ?, ?, ?)",
        (name, phone_number, messenger_id, json.dumps(preferences or {})),
    )
    return db.query_one("SELECT * FROM users WHERE user_id = ?", (uid,))


def ensure_user(
    phone_number: str | None = None,
    messenger_id: str | None = None,
    name: str | None = None,
) -> dict:
    """Find-or-create. Used at the start of every conversation."""
    existing = get_user_by_phone_or_profile_id(phone_number, messenger_id)
    if existing:
        return existing
    return create_user(name=name, phone_number=phone_number, messenger_id=messenger_id)


def update_user_preferences(user_id: int, preferences: dict) -> dict:
    db.execute(
        "UPDATE users SET preferences = ?, updated_at = datetime('now') WHERE user_id = ?",
        (json.dumps(preferences), user_id),
    )
    return db.query_one("SELECT * FROM users WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Products / discovery
# ---------------------------------------------------------------------------
def get_products_by_category_or_search(
    query: str | None = None,
    category: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Query the catalog by free-text search and/or category. In-stock first."""
    clauses = ["is_active = 1"]
    params: list[Any] = []
    if category:
        clauses.append("LOWER(category) = LOWER(?)")
        params.append(category)
    if query:
        clauses.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(category) LIKE ?)")
        like = f"%{query.lower()}%"
        params.extend([like, like, like])
    where = " AND ".join(clauses)
    params.append(limit)
    return db.query(
        f"SELECT * FROM products WHERE {where} "
        f"ORDER BY (stock_quantity > 0) DESC, price ASC LIMIT ?",
        params,
    )


def get_product(product_id: int) -> dict | None:
    return db.query_one("SELECT * FROM products WHERE product_id = ?", (product_id,))


def list_categories() -> list[str]:
    rows = db.query("SELECT DISTINCT category FROM products WHERE is_active = 1 ORDER BY category")
    return [r["category"] for r in rows]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def create_order(
    user_id: int,
    product_id: int,
    quantity: int = 1,
    delivery_address: str | None = None,
) -> dict:
    """Place an order after validating stock and pricing. Reserves stock."""
    product = get_product(product_id)
    if not product:
        return {"error": "product_not_found", "product_id": product_id}
    if quantity < 1:
        return {"error": "invalid_quantity", "quantity": quantity}
    if product["stock_quantity"] < quantity:
        return {
            "error": "insufficient_stock",
            "requested": quantity,
            "available": product["stock_quantity"],
            "product": product["name"],
        }

    unit_price = product["price"]
    total = round(unit_price * quantity, 2)

    with db.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO orders
               (user_id, product_id, quantity, unit_price, total_amount, currency,
                status, delivery_address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, product_id, quantity, unit_price, total, product["currency"],
             OrderStatus.PENDING_PAYMENT, delivery_address),
        )
        order_id = cur.lastrowid
        # Reserve stock immediately so two chats can't oversell.
        conn.execute(
            "UPDATE products SET stock_quantity = stock_quantity - ? WHERE product_id = ?",
            (quantity, product_id),
        )
        conn.execute(
            "INSERT INTO order_events (order_id, status, note) VALUES (?, ?, ?)",
            (order_id, OrderStatus.PENDING_PAYMENT, "Order created"),
        )

    return get_order(order_id)


def get_order(order_id: int) -> dict | None:
    order = db.query_one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    if not order:
        return None
    order["product"] = get_product(order["product_id"])
    order["events"] = db.query(
        "SELECT status, note, created_at FROM order_events WHERE order_id = ? ORDER BY event_id",
        (order_id,),
    )
    return order


def get_orders_for_user(user_id: int, limit: int = 10) -> list[dict]:
    return db.query(
        "SELECT * FROM orders WHERE user_id = ? ORDER BY order_id DESC LIMIT ?",
        (user_id, limit),
    )


def update_order_status(order_id: int, status: str, note: str | None = None) -> dict:
    """Advance an order through its lifecycle (drives tracking notifications)."""
    if status not in OrderStatus.ALL:
        return {"error": "invalid_status", "status": status, "allowed": OrderStatus.ALL}
    order = db.query_one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    if not order:
        return {"error": "order_not_found", "order_id": order_id}

    with db.get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = datetime('now') WHERE order_id = ?",
            (status, order_id),
        )
        conn.execute(
            "INSERT INTO order_events (order_id, status, note) VALUES (?, ?, ?)",
            (order_id, status, note),
        )
        # Restock on cancellation/refund.
        if status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            conn.execute(
                "UPDATE products SET stock_quantity = stock_quantity + ? WHERE product_id = ?",
                (order["quantity"], order["product_id"]),
            )
    return get_order(order_id)


def record_payment(order_id: int, payment_reference: str) -> dict:
    """Attach a payment reference and mark the order PAID."""
    db.execute(
        "UPDATE orders SET payment_reference = ?, status = ?, updated_at = datetime('now') "
        "WHERE order_id = ?",
        (payment_reference, OrderStatus.PAID, order_id),
    )
    db.execute(
        "INSERT INTO order_events (order_id, status, note) VALUES (?, ?, ?)",
        (order_id, OrderStatus.PAID, f"Payment confirmed: {payment_reference}"),
    )
    return get_order(order_id)


# ---------------------------------------------------------------------------
# Payment integration helper
# ---------------------------------------------------------------------------
def create_payment_link(order_id: int, method: str = "external") -> dict:
    """
    Produce a payment instruction for the order.

    method:
      * 'whatsapp_pay'  -> native WhatsApp Pay order_details payload (stub)
      * 'messenger_pay' -> Messenger checkout button payload (stub)
      * 'external'      -> hosted checkout URL
    """
    order = get_order(order_id)
    if not order:
        return {"error": "order_not_found", "order_id": order_id}

    if method == "external":
        url = f"{settings.payment_link_base}?order={order_id}&amt={order['total_amount']}"
        return {"method": "external", "url": url, "amount": order["total_amount"],
                "currency": order["currency"]}
    if method == "whatsapp_pay":
        return {"method": "whatsapp_pay", "order_id": order_id,
                "amount": order["total_amount"], "currency": order["currency"],
                "note": "Send as interactive order_details message via WhatsApp Cloud API."}
    if method == "messenger_pay":
        return {"method": "messenger_pay", "order_id": order_id,
                "amount": order["total_amount"], "currency": order["currency"],
                "note": "Attach a buy button / webview checkout via Messenger Send API."}
    return {"error": "unknown_method", "method": method}


# ---------------------------------------------------------------------------
# Messages / conversation context
# ---------------------------------------------------------------------------
def log_message(
    chat_id: str,
    user_id: int | None,
    content: str,
    channel: str = "whatsapp",
    direction: str = "in",
) -> dict:
    mid = db.execute(
        "INSERT INTO messages (chat_id, user_id, channel, direction, content) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, user_id, channel, direction, content),
    )
    return db.query_one("SELECT * FROM messages WHERE message_id = ?", (mid,))


def get_recent_messages(chat_id: str, limit: int = 12) -> list[dict]:
    rows = db.query(
        "SELECT * FROM messages WHERE chat_id = ? ORDER BY message_id DESC LIMIT ?",
        (chat_id, limit),
    )
    return list(reversed(rows))


def last_inbound_time(chat_id: str) -> str | None:
    row = db.query_one(
        "SELECT timestamp FROM messages WHERE chat_id = ? AND direction = 'in' "
        "ORDER BY message_id DESC LIMIT 1",
        (chat_id,),
    )
    return row["timestamp"] if row else None
