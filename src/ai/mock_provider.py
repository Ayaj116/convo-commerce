"""
Mock provider — a deterministic, rule-based 'brain' used for local demos,
CI and offline development. It exercises the exact same tool-calling loop the
real models use, so the agent code path is identical.

It reads the transcript, infers where in the ordering funnel the customer is,
and emits either a tool call or a customer-facing message.
"""
from __future__ import annotations

import json
import re

from src.ai.base import AIProvider, AIResponse, ToolCall

_GREET = re.compile(r"\b(hi|hello|hey|good (morning|afternoon|evening)|start)\b", re.I)
_TRACK = re.compile(r"\b(track|where.*order|status|delivery)\b", re.I)
_NUM = re.compile(r"\b(\d+)\b")


def _last_user(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "") or ""
    return ""


def _tool_results(messages: list[dict]) -> dict[str, object]:
    """Collect the most recent result for each tool that was called."""
    out: dict[str, object] = {}
    for m in messages:
        if m.get("role") == "tool":
            try:
                out[m["name"]] = json.loads(m["content"])
            except Exception:
                out[m["name"]] = m["content"]
    return out


def _called(messages: list[dict], name: str) -> bool:
    return any(m.get("role") == "tool" and m.get("name") == name for m in messages)


_counter = {"n": 0}


def _tid() -> str:
    _counter["n"] += 1
    return f"mock_{_counter['n']}"


class MockProvider(AIProvider):
    name = "mock"

    def generate(self, system: str, messages: list[dict], tools: list[dict]) -> AIResponse:
        text = _last_user(messages)
        results = _tool_results(messages)

        user = results.get("get_user_by_phone_or_profile_id") or {}
        user_id = user.get("user_id") if isinstance(user, dict) else None

        # 1) Always identify the user first.
        if not _called(messages, "get_user_by_phone_or_profile_id"):
            ident = _extract_identity(messages)
            return AIResponse(tool_calls=[ToolCall(_tid(),
                "get_user_by_phone_or_profile_id", ident)])

        name = user.get("name") if isinstance(user, dict) else None

        # 2) Pure greeting with no product intent yet -> warm welcome.
        if _GREET.search(text) and not _product_intent(text):
            hi = f"Hi {name}! " if name else "Hi there! "
            return AIResponse(text=(
                f"{hi}Welcome to the store 👋 I can help you find products and "
                f"place an order. What are you shopping for today?"))

        # 3) Tracking / aftersales path.
        if _TRACK.search(text) and not _called(messages, "get_order"):
            m = _NUM.search(text)
            if m:
                return AIResponse(tool_calls=[ToolCall(_tid(), "get_order",
                    {"order_id": int(m.group(1))})])
            return AIResponse(text="Happy to help track that! What's your order number?")

        if "get_order" in results:
            o = results["get_order"]
            if isinstance(o, dict) and o.get("order_id"):
                label = o.get("status", "processing").replace("_", " ").lower()
                return AIResponse(text=(
                    f"Order #{o['order_id']} ({o['product']['name']} ×{o['quantity']}) "
                    f"is currently *{label}*. Total {o['currency']} {o['total_amount']:.2f}. "
                    f"Anything else I can help with?"))
            return AIResponse(text="I couldn't find that order number — could you double-check it?")

        # 3) Product discovery.
        if not _called(messages, "get_products_by_category_or_search"):
            q = _extract_query(text)
            return AIResponse(tool_calls=[ToolCall(_tid(),
                "get_products_by_category_or_search", {"query": q})])

        products = results.get("get_products_by_category_or_search") or []
        if isinstance(products, list) and products and "create_order" not in results:
            # If the user picked a quantity/product, place the order.
            chosen = _match_product(text, products)
            qty = _extract_qty(text)
            if chosen and qty and user_id:
                return AIResponse(tool_calls=[ToolCall(_tid(), "create_order", {
                    "user_id": user_id, "product_id": chosen["product_id"],
                    "quantity": qty, "delivery_address": _extract_address(messages)})])
            # Otherwise present the shortlist.
            lines = [f"• {p['name']} — {p['currency']} {p['price']:.2f} "
                     f"({'in stock' if p['stock_quantity'] else 'out of stock'})"
                     for p in products[:4]]
            return AIResponse(text=(
                "Here's what I found:\n" + "\n".join(lines) +
                "\n\nWhich one would you like, and how many?"))

        # 4) Payment after order creation.
        if "create_order" in results and "create_payment_link" not in results:
            order = results["create_order"]
            if isinstance(order, dict) and order.get("order_id"):
                return AIResponse(tool_calls=[ToolCall(_tid(), "create_payment_link",
                    {"order_id": order["order_id"], "method": "external"})])
            if isinstance(order, dict) and order.get("error"):
                return AIResponse(text=_order_error_text(order))

        if "create_payment_link" in results:
            order = results.get("create_order", {})
            pay = results["create_payment_link"]
            oid = order.get("order_id") if isinstance(order, dict) else "?"
            total = order.get("total_amount", 0) if isinstance(order, dict) else 0
            url = pay.get("url", "") if isinstance(pay, dict) else ""
            return AIResponse(text=(
                f"You're all set! I've created order #{oid} for a total of "
                f"{order.get('currency','USD')} {total:.2f}. 🎉\n\n"
                f"Complete your payment here: {url}\n\n"
                f"Once payment clears I'll confirm and share tracking updates. "
                f"Thanks for shopping with us!"))

        # Fallback.
        return AIResponse(text="I'm here to help you find products and place an order. "
                               "What are you looking for today?")


# --- tiny heuristics --------------------------------------------------------
def _extract_identity(messages: list[dict]) -> dict:
    for m in messages:
        meta = m.get("_meta") or {}
        if meta.get("phone_number"):
            return {"phone_number": meta["phone_number"]}
        if meta.get("messenger_id"):
            return {"messenger_id": meta["messenger_id"]}
    return {}


def _product_intent(text: str) -> bool:
    return bool(re.search(r"\b(shoe|sneaker|boot|sandal|jacket|tee|shirt|vest|"
                          r"backpack|bag|sunglass|charger|buy|want|need|looking|"
                          r"order|shop|footwear|apparel|accessor|electronic)\w*",
                          text, re.I))


def _extract_query(text: str) -> str:
    t = text.lower()
    # Drop everything from the delivery instruction onward.
    t = re.split(r"\b(ship to|deliver to|delivery|address|send to)\b", t)[0]
    # Remove filler words and quantities.
    t = re.sub(r"\b(i'?ll|i|want|need|looking|for|some|a|an|the|buy|to|please|"
               r"show|me|take|of|get|would|like|can|you|pcs?|pieces?|units?)\b", " ", t)
    t = re.sub(r"\b\d+\b", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or text.strip()


def _extract_qty(text: str) -> int | None:
    m = re.search(r"\b(\d+)\b", text)
    return int(m.group(1)) if m else (1 if re.search(r"\b(one|a|an|this|that)\b", text, re.I) else None)


def _match_product(text: str, products: list[dict]) -> dict | None:
    low = text.lower()
    for p in products:
        if p["name"].lower() in low or any(w in low for w in p["name"].lower().split()):
            return p
    return products[0] if products else None


def _extract_address(messages: list[dict]) -> str | None:
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        cue = re.search(r"\b(?:ship to|deliver to|send to|address:?)\s*(.+)", content, re.I)
        if cue:
            return cue.group(1).strip()
        if re.search(r"\d+\s+\w+.*(st|street|ave|avenue|road|rd|lane|blvd)", content, re.I):
            return content.strip()
    return None


def _order_error_text(order: dict) -> str:
    err = order.get("error")
    if err == "insufficient_stock":
        return (f"Sorry — we only have {order['available']} of {order['product']} in stock "
                f"right now. Would you like that quantity instead?")
    if err == "product_not_found":
        return "Hmm, I couldn't find that product. Want me to show the options again?"
    return "Something went wrong placing that order — let's try again."
