"""
Internal tool calls, against the Supabase `commerce` schema.

LLM-exposed tools (see src/tools/registry.py):
  * get_user_by_phone_or_profile_id
  * get_products_by_category_or_search
  * create_order
  * update_order_status
  * get_order
  * get_orders_for_customer
  * create_payment_link
  * get_invoice

Internal only (called directly by the agent/gateway, never by the model):
  * ensure_customer_profile, ensure_conversation
  * log_message, get_recent_messages, message_already_processed
  * mark_payment_paid, create_invoice
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from config import settings
from src.db import database as db
from src.db.models import InvoiceStatus, MessageDirection, MessageType, OrderStatus, PaymentStatus
from src.tools import eta as eta_engine


# ---------------------------------------------------------------------------
# Customers / profiles / conversations
# ---------------------------------------------------------------------------
def _merge_profile(profile: dict, customer: dict | None) -> dict:
    return {
        "profile_id": profile["id"],
        "customer_id": customer["id"] if customer else profile["customer_id"],
        "channel": profile["channel"],
        "platform_user_id": profile["platform_user_id"],
        "display_name": profile.get("display_name"),
        "phone_number": profile.get("phone_number"),
        "full_name": customer["full_name"] if customer else None,
        "email": customer.get("email") if customer else None,
    }


def ensure_customer_profile(
    channel: str,
    platform_user_id: str,
    display_name: str | None = None,
    phone_number: str | None = None,
) -> dict:
    """Find-or-create a customer_profile (+ parent customer). Used at the
    start of every conversation. Internal — not LLM-exposed."""
    profile = db.select_one(
        "customer_profiles",
        {"channel": db.eq(channel), "platform_user_id": db.eq(platform_user_id)},
    )
    if profile:
        customer = db.select_one("customers", {"id": db.eq(profile["customer_id"])})
        return _merge_profile(profile, customer)

    customer = db.insert_one("customers", {"full_name": display_name or "New Customer"})
    profile = db.insert_one(
        "customer_profiles",
        {
            "customer_id": customer["id"],
            "channel": channel,
            "platform_user_id": platform_user_id,
            "display_name": display_name,
            "phone_number": phone_number,
        },
    )
    return _merge_profile(profile, customer)


def get_user_by_phone_or_profile_id(
    channel: str | None = None,
    platform_user_id: str | None = None,
    phone_number: str | None = None,
) -> dict | None:
    """Look up a customer by channel + platform id, or by WhatsApp phone number."""
    profile = None
    if channel and platform_user_id:
        profile = db.select_one(
            "customer_profiles",
            {"channel": db.eq(channel), "platform_user_id": db.eq(platform_user_id)},
        )
    elif phone_number:
        profile = db.select_one("customer_profiles", {"phone_number": db.eq(phone_number)})
    if not profile:
        return None
    customer = db.select_one("customers", {"id": db.eq(profile["customer_id"])})
    return _merge_profile(profile, customer)


def get_channel_profiles_for_customer(customer_id: str) -> list[dict]:
    """All channel identities (whatsapp/messenger) linked to a customer — used
    by notifications to know where to deliver a status update."""
    return db.select("customer_profiles", {"customer_id": db.eq(customer_id)})


def ensure_conversation(profile_id: str) -> dict:
    """Find the customer's open conversation or start a new one."""
    convo = db.select_one(
        "conversations", {"profile_id": db.eq(profile_id), "status": db.eq("OPEN")}
    )
    if convo:
        return convo
    return db.insert_one("conversations", {"profile_id": profile_id, "status": "OPEN"})


# ---------------------------------------------------------------------------
# Messages / idempotency
# ---------------------------------------------------------------------------
def message_already_processed(platform_message_id: str | None) -> bool:
    """True if we've already logged a message with this platform id — guards
    against Meta's at-least-once webhook redelivery causing double-processing."""
    if not platform_message_id:
        return False
    return db.select_one("messages", {"platform_message_id": db.eq(platform_message_id)}) is not None


def log_message(
    conversation_id: str,
    content: str,
    direction: str = MessageDirection.INBOUND,
    message_type: str = MessageType.TEXT,
    platform_message_id: str | None = None,
) -> dict:
    data: dict[str, Any] = {
        "conversation_id": conversation_id,
        "direction": direction,
        "message_type": message_type,
        "message": content,
    }
    if platform_message_id:
        data["platform_message_id"] = platform_message_id
    return db.insert_one("messages", data)


def get_recent_messages(conversation_id: str, limit: int = 12) -> list[dict]:
    rows = db.select(
        "messages", {"conversation_id": db.eq(conversation_id)}, order="created_at.desc", limit=limit
    )
    return list(reversed(rows))


def last_inbound_time_for_profile(channel: str, platform_user_id: str) -> str | None:
    """Used by the connectors to enforce the WhatsApp/Messenger 24h window."""
    profile = db.select_one(
        "customer_profiles", {"channel": db.eq(channel), "platform_user_id": db.eq(platform_user_id)}
    )
    if not profile:
        return None
    convo = db.select_one(
        "conversations", {"profile_id": db.eq(profile["id"]), "status": db.eq("OPEN")}
    )
    if not convo:
        return None
    rows = db.select(
        "messages",
        {"conversation_id": db.eq(convo["id"]), "direction": db.eq(MessageDirection.INBOUND)},
        order="created_at.desc",
        limit=1,
    )
    return rows[0]["created_at"] if rows else None


# ---------------------------------------------------------------------------
# Products / discovery
# ---------------------------------------------------------------------------
def _sanitize_query(text: str) -> str:
    """Strip characters that would break PostgREST's or=(...) grouping syntax."""
    return text.replace("(", " ").replace(")", " ").replace(",", " ").strip()


def get_products_by_category_or_search(
    query: str | None = None,
    category: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Search the catalog by free text and/or category. In-stock items first."""
    filters: dict[str, str] = {"is_active": db.eq(True)}
    if category:
        filters["category"] = db.eq(category)
    if query:
        q = _sanitize_query(query)
        if q:
            filters["or"] = f"(name.ilike.*{q}*,description.ilike.*{q}*,sku.ilike.*{q}*)"

    # Overfetch and sort client-side: PostgREST can't express "in-stock first,
    # cheapest within that" as a single order key without a generated column.
    fetch_limit = max(limit * 3, 20)
    rows = db.select("products", filters, order="price.asc", limit=fetch_limit)
    rows.sort(key=lambda p: (p.get("stock_quantity", 0) <= 0, p["price"]))
    return rows[:limit]


def get_product(product_id: str) -> dict | None:
    return db.select_one("products", {"id": db.eq(product_id)})


def list_categories() -> list[str]:
    rows = db.select("products", {"is_active": db.eq(True)}, columns="category")
    return sorted({r["category"] for r in rows if r.get("category")})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def _order_number() -> str:
    return f"ORD-{uuid.uuid4().hex[:8].upper()}"


def _invoice_number() -> str:
    return f"INV-{uuid.uuid4().hex[:8].upper()}"


def _fail_order(order_id: str, remarks: str) -> None:
    """No dedicated FAILED order status exists in the schema — cancel the
    order instead and record why, rather than leaving it silently broken."""
    try:
        db.update("orders", {"id": db.eq(order_id)}, {"status": OrderStatus.CANCELLED})
        db.insert_one(
            "order_status_history",
            {"order_id": order_id, "status": OrderStatus.CANCELLED, "changed_by": "system",
             "remarks": f"Order could not be completed: {remarks}"},
        )
    except db.DatabaseError:
        pass


def create_order(
    customer_id: str,
    items: list[dict],
    delivery_address: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Place an order after the customer confirms product(s), quantity and
    delivery address. All pricing is computed server-side from live product
    rows — never trust price/tax/total from the caller."""
    if not items:
        return {"error": "no_items"}

    resolved = []
    for item in items:
        product_id = item.get("product_id")
        try:
            quantity = int(item.get("quantity", 1))
        except (TypeError, ValueError):
            return {"error": "invalid_quantity", "product_id": product_id, "quantity": item.get("quantity")}
        if quantity < 1:
            return {"error": "invalid_quantity", "product_id": product_id, "quantity": quantity}

        product = get_product(product_id)
        if not product or not product.get("is_active", True):
            return {"error": "product_not_found", "product_id": product_id}
        if product.get("stock_quantity", 0) < quantity:
            return {
                "error": "insufficient_stock",
                "product_id": product_id,
                "product": product["name"],
                "requested": quantity,
                "available": product.get("stock_quantity", 0),
            }

        unit_price = float(product["price"])
        tax_percent = float(product.get("tax_percent") or 0)
        line_subtotal = round(unit_price * quantity, 2)
        line_tax = round(line_subtotal * tax_percent / 100, 2)
        resolved.append({
            "product_id": product_id,
            "product_name": product["name"],
            "quantity": quantity,
            "unit_price": unit_price,
            "subtotal": line_subtotal,
            "tax": line_tax,
            "total": round(line_subtotal + line_tax, 2),
        })

    subtotal = round(sum(r["subtotal"] for r in resolved), 2)
    tax = round(sum(r["tax"] for r in resolved), 2)
    total = round(subtotal + tax, 2)

    # 1) Insert the order shell first — safe to leave/mark FAILED if a later
    #    step breaks, since it has no side effects on other data yet.
    order_row = db.insert_one("orders", {
        "order_number": _order_number(),
        "customer_id": customer_id,
        "conversation_id": conversation_id,
        "status": OrderStatus.CREATED,
        "currency": settings.currency,
        "subtotal": subtotal,
        "tax": tax,
        "discount": 0,
        "total": total,
        "delivery_address": delivery_address,
    })
    order_id = order_row["id"]

    # 2) Insert line items.
    try:
        db.insert("order_items", [
            {
                "order_id": order_id,
                "product_id": r["product_id"],
                "quantity": r["quantity"],
                "unit_price": r["unit_price"],
                "discount": 0,
                "tax": r["tax"],
                "total": r["total"],
            }
            for r in resolved
        ])
    except db.DatabaseError as exc:
        _fail_order(order_id, f"order_items insert failed: {exc}")
        return {"error": "order_failed", "detail": str(exc)}

    # 3) Atomically decrement stock per item (DB-side function — no
    #    read-then-write race). Roll back anything already decremented if a
    #    later item loses the race.
    decremented: list[dict] = []
    for r in resolved:
        rows = db.rpc("decrement_stock", {"p_product_id": r["product_id"], "p_qty": r["quantity"]})
        if not rows:
            for done in decremented:
                db.rpc("increment_stock", {"p_product_id": done["product_id"], "p_qty": done["quantity"]})
            _fail_order(order_id, f"stock conflict on product {r['product_id']}")
            return {
                "error": "insufficient_stock",
                "product_id": r["product_id"],
                "product": r["product_name"],
            }
        decremented.append(r)

    # 4) Best-effort initial history row — doesn't block order visibility.
    try:
        db.insert_one("order_status_history", {
            "order_id": order_id, "status": OrderStatus.CREATED,
            "changed_by": "system", "remarks": "Order created",
        })
    except db.DatabaseError:
        pass

    return get_order(order_id)


def get_order(order_id: str) -> dict | None:
    order = db.select_one("orders", {"id": db.eq(order_id)})
    if not order:
        return None
    items = db.select("order_items", {"order_id": db.eq(order_id)})
    for item in items:
        item["product"] = get_product(item["product_id"])
    order["items"] = items
    order["events"] = db.select(
        "order_status_history", {"order_id": db.eq(order_id)}, order="created_at.asc"
    )
    return order


def get_orders_for_customer(customer_id: str, limit: int = 10) -> list[dict]:
    return db.select(
        "orders", {"customer_id": db.eq(customer_id)}, order="created_at.desc", limit=limit
    )


def update_order_status(
    order_id: str, status: str, note: str | None = None, changed_by: str = "agent"
) -> dict:
    """Advance an order through its lifecycle (drives tracking notifications)."""
    if status not in OrderStatus.SETTABLE:
        return {"error": "invalid_status", "status": status, "allowed": OrderStatus.SETTABLE}
    order = db.select_one("orders", {"id": db.eq(order_id)})
    if not order:
        return {"error": "order_not_found", "order_id": order_id}

    db.update("orders", {"id": db.eq(order_id)}, {"status": status})
    db.insert_one("order_status_history", {
        "order_id": order_id, "status": status, "changed_by": changed_by, "remarks": note,
    })

    if status in OrderStatus.RESTOCKING:
        for item in db.select("order_items", {"order_id": db.eq(order_id)}):
            db.rpc("increment_stock", {"p_product_id": item["product_id"], "p_qty": item["quantity"]})

    return get_order(order_id)


def format_tracking_remark(number: str) -> str:
    return f"tracking:{number}"


def parse_tracking_remark(remarks: str | None) -> str | None:
    prefix = "tracking:"
    if remarks and remarks.startswith(prefix):
        return remarks[len(prefix):].strip()
    return None


def get_latest_tracking_number(order_id: str) -> str | None:
    rows = db.select(
        "order_status_history",
        {"order_id": db.eq(order_id), "status": db.eq(OrderStatus.SHIPPED)},
        order="created_at.desc",
        limit=1,
    )
    return parse_tracking_remark(rows[0].get("remarks")) if rows else None


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def create_payment_link(order_id: str, method: str = "external") -> dict:
    """
    Produce a payment instruction for the order and record a PENDING payment.

    method:
      * 'whatsapp_pay'  -> native WhatsApp Pay order_details payload (stub)
      * 'messenger_pay' -> Messenger checkout button payload (stub)
      * 'external'      -> hosted checkout URL
    """
    order = get_order(order_id)
    if not order:
        return {"error": "order_not_found", "order_id": order_id}

    if method == "external":
        url = f"{settings.payment_link_base}?order={order_id}&amt={order['total']}"
        result = {"method": "external", "url": url, "amount": order["total"], "currency": order["currency"]}
    elif method == "whatsapp_pay":
        result = {
            "method": "whatsapp_pay", "order_id": order_id,
            "amount": order["total"], "currency": order["currency"],
            "note": "Send as interactive order_details message via WhatsApp Cloud API.",
        }
    elif method == "messenger_pay":
        result = {
            "method": "messenger_pay", "order_id": order_id,
            "amount": order["total"], "currency": order["currency"],
            "note": "Attach a buy button / webview checkout via Messenger Send API.",
        }
    else:
        return {"error": "unknown_method", "method": method}

    # payment_method/payment_provider are a fixed DB vocabulary (CARD/CASH/UPI/...,
    # STRIPE/RAZORPAY/PAYPAL/CASH/OTHER/...) distinct from our `method` param,
    # which describes *how the link is delivered* (whatsapp_pay/messenger_pay/
    # external). No real gateway is wired up yet, so we record a generic
    # card-via-hosted-link payment and keep `method` in the returned payload.
    payment = db.insert_one("payments", {
        "order_id": order_id,
        "payment_method": "CARD",
        "amount": order["total"],
        "currency": order["currency"],
        "payment_provider": "OTHER",
        "status": PaymentStatus.PENDING,
    })
    if order["status"] == OrderStatus.CREATED:
        update_order_status(order_id, OrderStatus.PENDING_PAYMENT, note="Payment link issued", changed_by="system")

    result["payment_id"] = payment["id"]
    return result


def mark_payment_paid(payment_id: str, payment_reference: str | None = None) -> dict:
    """Internal only — invoked from an ops/payment-confirmation endpoint,
    never from the LLM tool loop (real confirmation should come from a
    payment gateway or ops action, not the customer talking the bot into it)."""
    payment = db.select_one("payments", {"id": db.eq(payment_id)})
    if not payment:
        return {"error": "payment_not_found", "payment_id": payment_id}

    db.update("payments", {"id": db.eq(payment_id)}, {
        "status": PaymentStatus.SUCCESS,
        "paid_at": datetime.now(timezone.utc).isoformat(),
        "payment_reference": payment_reference,
    })
    order_id = payment["order_id"]
    update_order_status(
        order_id, OrderStatus.PAID,
        note=f"Payment confirmed: {payment_reference or payment_id}", changed_by="system",
    )
    invoice = create_invoice(order_id)
    db.update("payments", {"id": db.eq(payment_id)}, {"invoice_id": invoice["id"]})
    return get_order(order_id)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
def create_invoice(order_id: str) -> dict:
    """Internal — auto-invoked once a payment is confirmed, so the invoice
    is always created already-PAID (the schema has no unpaid/draft state)."""
    existing = db.select_one("invoices", {"order_id": db.eq(order_id)})
    if existing:
        return existing
    order = db.select_one("orders", {"id": db.eq(order_id)})
    if not order:
        raise ValueError(f"cannot create invoice: order {order_id} not found")
    return db.insert_one("invoices", {
        "order_id": order_id,
        "invoice_number": _invoice_number(),
        "status": InvoiceStatus.PAID,
        "issue_date": date.today().isoformat(),
        "subtotal": order["subtotal"],
        "tax": order["tax"],
        "total": order["total"],
    })


def get_invoice(order_id: str) -> dict:
    """Fetch invoice details for an order. Use for 'send me the invoice' /
    'invoice details' style requests."""
    order = db.select_one("orders", {"id": db.eq(order_id)})
    if not order:
        return {"error": "order_not_found", "order_id": order_id}
    invoice = db.select_one("invoices", {"order_id": db.eq(order_id)})
    if not invoice:
        return {
            "status": "not_available",
            "reason": "payment_pending",
            "message": "This order's invoice will be issued once payment is confirmed.",
        }
    invoice["order_number"] = order["order_number"]
    invoice["currency"] = order["currency"]
    return invoice


# ---------------------------------------------------------------------------
# Delivery addresses (registered per customer — power the ETA engine)
# ---------------------------------------------------------------------------
def save_customer_address(
    customer_id: str,
    address_line: str,
    label: str | None = "Home",
    city: str | None = None,
    postal_code: str | None = None,
    make_default: bool = True,
) -> dict:
    """Register (or update) a delivery address for a customer so future ETAs
    can be computed without re-asking. Falls back gracefully if the
    customer_addresses table (migration_003) hasn't been applied — the caller
    can still pass the address string straight to estimate_eta."""
    try:
        if make_default:
            # Clear any existing default first (partial unique index enforces one).
            existing_defaults = db.select(
                "customer_addresses",
                {"customer_id": db.eq(customer_id), "is_default": db.eq(True)},
            )
            for row in existing_defaults:
                db.update("customer_addresses", {"id": db.eq(row["id"])}, {"is_default": False})
        row = db.insert_one("customer_addresses", {
            "customer_id": customer_id,
            "label": label,
            "address_line": address_line,
            "city": city,
            "postal_code": postal_code,
            "is_default": make_default,
        })
        return row
    except db.DatabaseError as exc:
        # Table not migrated yet — degrade to a non-persistent echo so the
        # conversation can continue (ETA still works off the address string).
        return {
            "persisted": False,
            "reason": "customer_addresses table not available — run migration_003.sql",
            "detail": str(exc),
            "address_line": address_line,
        }


def get_default_address(customer_id: str) -> dict | None:
    """The customer's default (or most recent) registered delivery address."""
    try:
        row = db.select_one(
            "customer_addresses",
            {"customer_id": db.eq(customer_id), "is_default": db.eq(True)},
        )
        if row:
            return row
        rows = db.select(
            "customer_addresses", {"customer_id": db.eq(customer_id)},
            order="created_at.desc", limit=1,
        )
        return rows[0] if rows else None
    except db.DatabaseError:
        return None


def _resolve_address(
    delivery_address: str | None = None,
    customer_id: str | None = None,
    order_id: str | None = None,
) -> str | None:
    """Pick the best address to quote an ETA against: an explicit one wins,
    then the order's address, then the customer's registered default."""
    if delivery_address and delivery_address.strip():
        return delivery_address
    if order_id:
        order = db.select_one("orders", {"id": db.eq(order_id)})
        if order and order.get("delivery_address"):
            return order["delivery_address"]
    if customer_id:
        addr = get_default_address(customer_id)
        if addr:
            return addr.get("address_line")
    return None


def estimate_eta(
    delivery_address: str | None = None,
    customer_id: str | None = None,
    order_id: str | None = None,
) -> dict:
    """Delivery ETA for a customer.

    * Pre-checkout: pass delivery_address and/or customer_id -> a time *window*
      ('40–55 min') the customer can decide on.
    * Post-checkout: pass order_id -> a *promised arrival time* anchored to when
      the order was placed, and persisted on the order as promised_eta.
    """
    from datetime import datetime

    address = _resolve_address(delivery_address, customer_id, order_id)

    anchor = None
    if order_id:
        order = db.select_one("orders", {"id": db.eq(order_id)})
        if order and order.get("created_at"):
            try:
                anchor = datetime.fromisoformat(order["created_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                anchor = None

    result = eta_engine.compute_eta(address, anchor=anchor)

    # Post-checkout: remember the promised time so follow-ups quote the same ETA.
    if order_id and result.get("available"):
        try:
            db.update("orders", {"id": db.eq(order_id)},
                      {"promised_eta": result["promised_by"]})
        except db.DatabaseError:
            pass  # promised_eta column not migrated — non-fatal
    return result


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
def process_refund(order_id: str, reason: str | None = None, changed_by: str = "agent") -> dict:
    """Refund a paid order: mark its successful payment REFUNDED, cancel the
    order (which restocks it), and void the invoice. Idempotent-ish — refunding
    an already-refunded order is reported, not double-applied."""
    order = db.select_one("orders", {"id": db.eq(order_id)})
    if not order:
        return {"error": "order_not_found", "order_id": order_id}

    payment = db.select_one(
        "payments", {"order_id": db.eq(order_id), "status": db.eq(PaymentStatus.SUCCESS)}
    )
    if not payment:
        already = db.select_one(
            "payments", {"order_id": db.eq(order_id), "status": db.eq(PaymentStatus.REFUNDED)}
        )
        if already:
            return {"status": "already_refunded", "order_id": order_id,
                    "amount": already["amount"], "currency": already["currency"]}
        return {"error": "no_successful_payment", "order_id": order_id,
                "message": "No captured payment to refund for this order."}

    db.update("payments", {"id": db.eq(payment["id"])}, {"status": PaymentStatus.REFUNDED})

    # Cancelling restocks the items (OrderStatus.RESTOCKING includes CANCELLED).
    update_order_status(
        order_id, OrderStatus.CANCELLED,
        note=f"Refunded: {reason or 'customer request'}", changed_by=changed_by,
    )

    # Void the invoice if one was issued.
    invoice = db.select_one("invoices", {"order_id": db.eq(order_id)})
    if invoice and invoice.get("status") != InvoiceStatus.VOID:
        try:
            db.update("invoices", {"id": db.eq(invoice["id"])}, {"status": InvoiceStatus.VOID})
        except db.DatabaseError:
            pass

    return {
        "status": "refunded",
        "order_id": order_id,
        "order_number": order["order_number"],
        "amount": payment["amount"],
        "currency": payment["currency"],
        "reason": reason or "customer request",
    }


# ---------------------------------------------------------------------------
# Recommendations (personalised from order history)
# ---------------------------------------------------------------------------
def recommend_for_customer(customer_id: str, limit: int = 4) -> dict:
    """Recommend products for a returning customer.

    Primary signal is the customer's own history: the products they've ordered
    before, most-ordered first (great for food re-orders). If they have no
    history (or too few), top up with popular in-stock catalog items so there's
    always something to suggest."""
    orders = db.select("orders", {"customer_id": db.eq(customer_id)},
                       order="created_at.desc", limit=25)
    order_ids = [o["id"] for o in orders]

    reorder: list[dict] = []
    counts: dict[str, int] = {}
    if order_ids:
        items = db.select("order_items", {"order_id": db.in_(order_ids)})
        for it in items:
            counts[it["product_id"]] = counts.get(it["product_id"], 0) + int(it.get("quantity", 1))
        for product_id, qty in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            product = get_product(product_id)
            if product and product.get("is_active", True) and product.get("stock_quantity", 0) > 0:
                reorder.append({
                    "product_id": product_id,
                    "name": product["name"],
                    "price": product["price"],
                    "times_ordered": qty,
                    "reason": "You've ordered this before",
                })
            if len(reorder) >= limit:
                break

    # Fill remaining slots with popular in-stock items the customer hasn't got yet.
    picks = list(reorder)
    if len(picks) < limit:
        seen = {r["product_id"] for r in picks}
        popular = get_products_by_category_or_search(limit=limit * 2)
        for p in popular:
            if p["id"] in seen:
                continue
            picks.append({
                "product_id": p["id"],
                "name": p["name"],
                "price": p["price"],
                "reason": "Popular right now",
            })
            if len(picks) >= limit:
                break

    return {
        "returning_customer": bool(reorder),
        "recommendations": picks[:limit],
    }
