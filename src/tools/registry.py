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
        "description": "Look up a customer by their WhatsApp phone number or Messenger profile id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string", "description": "E.164 phone, WhatsApp users"},
                "messenger_id": {"type": "string", "description": "Messenger PSID"},
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
        "description": "Place an order after the customer has confirmed product, quantity and delivery address. Validates stock and pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "product_id": {"type": "integer"},
                "quantity": {"type": "integer"},
                "delivery_address": {"type": "string"},
            },
            "required": ["user_id", "product_id", "quantity"],
        },
    },
    {
        "name": "update_order_status",
        "description": "Advance an order's status. Allowed: PENDING_PAYMENT, PAID, PACKED, SHIPPED, OUT_FOR_DELIVERY, DELIVERED, CANCELLED, REFUNDED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "status": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["order_id", "status"],
        },
    },
    {
        "name": "get_order",
        "description": "Fetch a single order with its product and full status history. Use for tracking and aftersales.",
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "integer"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "create_payment_link",
        "description": "Generate a payment instruction for an order. method: whatsapp_pay | messenger_pay | external.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "method": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "log_message",
        "description": "Persist a conversation message for context and audit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string"},
                "user_id": {"type": "integer"},
                "content": {"type": "string"},
                "channel": {"type": "string"},
                "direction": {"type": "string"},
            },
            "required": ["chat_id", "content"],
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
    "create_payment_link": tools.create_payment_link,
    "log_message": tools.log_message,
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
