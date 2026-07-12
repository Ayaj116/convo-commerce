"""
ADK-facing tool functions for the Convo-Commerce agents.

These are thin, well-documented wrappers around the validated business logic in
`src/tools/tools.py`. ADK builds each tool's JSON schema from the function
signature and docstring, so the type hints and docstrings here ARE the contract
the model sees — keep them precise.

The customer's identity (customer_id, conversation_id, channel) is NOT passed by
the model. It's injected once per conversation into ADK session state by the
runner and read here via `tool_context.state`. This keeps identity server-side
and out of the model's reach — the model can't spoof a different customer.
"""
from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from src.tools import tools


# --- identity helpers (read from session state, never from the model) -------
def _customer_id(ctx: ToolContext) -> str | None:
    return ctx.state.get("customer_id")


def _conversation_id(ctx: ToolContext) -> str | None:
    return ctx.state.get("conversation_id")


# --- profile & recommendations ----------------------------------------------
def get_my_profile(tool_context: ToolContext) -> dict:
    """Get the current customer's profile: name, whether they are a returning
    customer, their registered default delivery address, and recent orders.
    Call this at the start of a conversation to greet returning customers and
    decide whether to offer a re-order."""
    customer_id = _customer_id(tool_context)
    if not customer_id:
        return {"error": "no_identity"}
    orders = tools.get_orders_for_customer(customer_id, limit=5)
    address = tools.get_default_address(customer_id)
    return {
        "customer_id": customer_id,
        "channel": tool_context.state.get("channel"),
        "display_name": tool_context.state.get("display_name"),
        "returning_customer": bool(orders),
        "recent_order_count": len(orders),
        "registered_address": address.get("address_line") if address else None,
    }


def recommend_for_me(tool_context: ToolContext) -> dict:
    """Personalised recommendations for the current customer based on their
    previous orders (falls back to popular items for new customers). Use to
    suggest a re-order or upsell."""
    customer_id = _customer_id(tool_context)
    if not customer_id:
        return {"error": "no_identity"}
    return tools.recommend_for_customer(customer_id)


# --- menu discovery ----------------------------------------------------------
def find_menu_items(query: str = "", category: str = "") -> dict:
    """Search the food catalog by free text and/or category (e.g. query='chicken'
    or category='Produce'). Returns real, in-stock items first with their id,
    name, price and stock. Never invent items or prices — only quote these."""
    items = tools.get_products_by_category_or_search(query=query or None, category=category or None)
    return {"count": len(items), "items": items}


# --- delivery address & ETA --------------------------------------------------
def save_my_address(
    address_line: str,
    label: str = "Home",
    city: str = "",
    postal_code: str = "",
    tool_context: ToolContext = None,  # type: ignore[assignment]
) -> dict:
    """Register/update the current customer's default delivery address so future
    ETAs and orders don't need to re-ask. Call this once the customer gives a
    delivery address."""
    customer_id = _customer_id(tool_context)
    if not customer_id:
        return {"error": "no_identity"}
    return tools.save_customer_address(
        customer_id, address_line, label=label or "Home",
        city=city or None, postal_code=postal_code or None,
    )


def delivery_eta(delivery_address: str = "", tool_context: ToolContext = None) -> dict:  # type: ignore[assignment]
    """Estimate the delivery ETA BEFORE checkout as a time window (e.g.
    '40-55 min'). Pass delivery_address if the customer just gave one; otherwise
    it uses their registered default address. Quote window_text to the customer."""
    customer_id = _customer_id(tool_context) if tool_context else None
    return tools.estimate_eta(delivery_address=delivery_address or None, customer_id=customer_id)


# --- ordering ----------------------------------------------------------------
def place_order(
    product_ids: list[str],
    quantities: list[int],
    delivery_address: str = "",
    tool_context: ToolContext = None,  # type: ignore[assignment]
) -> dict:
    """Place an order once the customer has CONFIRMED items, quantities and a
    delivery address. product_ids and quantities are parallel arrays (same
    length, one entry per line item). Pricing is computed server-side. Returns
    the created order (with order_id, total and status). Do not call until the
    customer has explicitly confirmed."""
    customer_id = _customer_id(tool_context)
    if not customer_id:
        return {"error": "no_identity"}
    if len(product_ids) != len(quantities):
        return {"error": "mismatched_items", "message": "product_ids and quantities must be the same length"}
    items: list[dict[str, Any]] = [
        {"product_id": pid, "quantity": qty} for pid, qty in zip(product_ids, quantities)
    ]
    order = tools.create_order(
        customer_id=customer_id,
        items=items,
        delivery_address=delivery_address or None,
        conversation_id=_conversation_id(tool_context),
    )
    # Persist the address for future ETAs/orders if a fresh one was given.
    if delivery_address and isinstance(order, dict) and order.get("id"):
        tools.save_customer_address(customer_id, delivery_address)
    return order


def checkout(order_id: str, method: str = "external", tool_context: ToolContext = None) -> dict:  # type: ignore[assignment]
    """Start checkout for an order: create a secure payment link and compute the
    PROMISED delivery time (post-checkout ETA anchored to the order). method is
    one of 'external', 'whatsapp_pay', 'messenger_pay'. Share the payment link
    and the promised_by time. NEVER tell the customer payment is confirmed — that
    happens only when our systems confirm it and we message them automatically."""
    payment = tools.create_payment_link(order_id, method=method or "external")
    eta = tools.estimate_eta(order_id=order_id)
    return {"payment": payment, "eta": eta}


# --- tracking / follow-ups / invoice ----------------------------------------
def order_status(order_id: str) -> dict:
    """Look up one order's current status, items, promised ETA and history. Use
    for 'where is my order' / follow-up questions."""
    order = tools.get_order(order_id)
    if not order:
        return {"error": "order_not_found", "order_id": order_id}
    return {
        "order_id": order["id"],
        "order_number": order["order_number"],
        "status": order["status"],
        "total": order["total"],
        "currency": order["currency"],
        "promised_eta": order.get("promised_eta"),
        "items": [
            {"name": (it.get("product") or {}).get("name"), "quantity": it["quantity"]}
            for it in order.get("items", [])
        ],
    }


def my_orders(tool_context: ToolContext) -> dict:
    """List the current customer's recent orders (id, number, status, total).
    Use for 'show my orders' / 'what did I order' requests."""
    customer_id = _customer_id(tool_context)
    if not customer_id:
        return {"error": "no_identity"}
    orders = tools.get_orders_for_customer(customer_id)
    return {"count": len(orders), "orders": [
        {"order_id": o["id"], "order_number": o["order_number"],
         "status": o["status"], "total": o["total"]}
        for o in orders
    ]}


def get_order_invoice(order_id: str) -> dict:
    """Fetch invoice details (number, amounts, status) for an order. If payment
    isn't confirmed yet, tell the customer the invoice is issued on payment."""
    return tools.get_invoice(order_id)


# --- refunds -----------------------------------------------------------------
def refund_order(order_id: str, reason: str = "", tool_context: ToolContext = None) -> dict:  # type: ignore[assignment]
    """Process a refund for a paid order (refunds the payment, cancels &
    restocks the order, voids the invoice). Confirm the order and reason with
    the customer before calling. Returns the refunded amount."""
    return tools.process_refund(order_id, reason=reason or None)
