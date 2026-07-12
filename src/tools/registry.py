"""
Tool registry.

A single, provider-agnostic description of every tool the model may call:
  * SCHEMAS  — JSON-Schema definitions (converted per-provider in src/ai).
  * dispatch — routes a tool name + args dict to the real implementation.

This is the contract shared by Claude, OpenAI and Gemini adapters.
"""
from __future__ import annotations

from typing import Any, Callable

from src.tools import tools

# JSON-Schema tool definitions (Anthropic-style; adapters reshape as needed).
SCHEMAS: list[dict] = [
    {
        "name": "get_user_by_phone_or_profile_id",
        "description": "Look up a customer by their channel identity (channel + platform_user_id) or WhatsApp phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "'whatsapp' or 'messenger'"},
                "platform_user_id": {"type": "string", "description": "WhatsApp phone number or Messenger PSID"},
                "phone_number": {"type": "string", "description": "E.164 phone, alternative to channel+platform_user_id"},
            },
        },
    },
    {
        "name": "get_products_by_category_or_search",
        "description": "Search the product catalog by free text and/or category. Returns in-stock items first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search, e.g. 'running shoes'"},
                "category": {"type": "string", "description": "Exact category filter, e.g. 'Footwear'"},
                "limit": {"type": "integer", "description": "Max results (default 8)"},
            },
        },
    },
    {
        "name": "create_order",
        "description": (
            "Place an order after the customer has confirmed the product(s), quantities and "
            "delivery address. Supports multiple line items in one order. Validates stock and "
            "computes pricing server-side — never invent prices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "items": {
                    "type": "array",
                    "description": "One entry per distinct product being ordered.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "quantity": {"type": "integer"},
                        },
                        "required": ["product_id", "quantity"],
                    },
                },
                "delivery_address": {"type": "string"},
            },
            "required": ["customer_id", "items"],
        },
    },
    {
        "name": "update_order_status",
        "description": "Advance an order's status. Allowed: CREATED, PENDING_PAYMENT, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "status": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["order_id", "status"],
        },
    },
    {
        "name": "get_order",
        "description": "Fetch a single order with its line items and full status history. Use for tracking and aftersales.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_orders_for_customer",
        "description": "List a customer's recent orders. Use for 'show my orders' / 'what have I bought' requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "create_payment_link",
        "description": "Generate a payment instruction for an order. method: whatsapp_pay | messenger_pay | external.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "method": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "get_invoice",
        "description": "Fetch invoice details (invoice number, amounts, status) for an order. Use for 'send me the invoice' / invoice detail requests.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "estimate_eta",
        "description": (
            "Estimate the delivery ETA for the customer. Pre-checkout: pass "
            "delivery_address and/or customer_id to get a time window ('40-55 min'). "
            "Post-checkout: pass order_id to get the promised arrival time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "delivery_address": {"type": "string"},
                "customer_id": {"type": "string"},
                "order_id": {"type": "string"},
            },
        },
    },
    {
        "name": "save_customer_address",
        "description": "Register/update a customer's default delivery address so future ETAs need no re-asking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "address_line": {"type": "string"},
                "label": {"type": "string", "description": "e.g. Home, Office"},
                "city": {"type": "string"},
                "postal_code": {"type": "string"},
            },
            "required": ["customer_id", "address_line"],
        },
    },
    {
        "name": "process_refund",
        "description": "Refund a paid order (marks the payment REFUNDED, cancels+restocks the order, voids the invoice). Use for refund requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "recommend_for_customer",
        "description": "Personalised product recommendations for a returning customer, based on their previous orders (falls back to popular items). Use it to greet returning customers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max recommendations (default 4)"},
            },
            "required": ["customer_id"],
        },
    },
]

# name -> callable
REGISTRY: dict[str, Callable[..., Any]] = {
    "get_user_by_phone_or_profile_id": tools.get_user_by_phone_or_profile_id,
    "get_products_by_category_or_search": tools.get_products_by_category_or_search,
    "create_order": tools.create_order,
    "update_order_status": tools.update_order_status,
    "get_order": tools.get_order,
    "get_orders_for_customer": tools.get_orders_for_customer,
    "create_payment_link": tools.create_payment_link,
    "get_invoice": tools.get_invoice,
    "estimate_eta": tools.estimate_eta,
    "save_customer_address": tools.save_customer_address,
    "process_refund": tools.process_refund,
    "recommend_for_customer": tools.recommend_for_customer,
}


def dispatch(name: str, arguments: dict) -> Any:
    """Execute a tool by name with keyword arguments."""
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": "unknown_tool", "tool": name}
    try:
        return fn(**(arguments or {}))
    except TypeError as exc:
        return {"error": "bad_arguments", "tool": name, "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surface any failure to the model gracefully
        return {"error": "tool_failed", "tool": name, "detail": str(exc)}
