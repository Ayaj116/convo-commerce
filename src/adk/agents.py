"""
The Convo-Commerce multi-agent system (Google ADK).

Topology — a root orchestrator that delegates to five specialists:

    convo_commerce_root  (router + greeter)
    ├── ordering_agent          discovery -> cart -> address/ETA -> place order
    ├── checkout_agent          payment link + promised delivery time
    ├── tracking_agent          order status, follow-ups, invoices
    ├── refund_agent            refunds / aftersales
    └── recommendation_agent    personalised re-orders from history

Each specialist is an LlmAgent with only the tools it needs. The root uses ADK's
built-in agent transfer (sub_agents) to hand a conversation to the right
specialist based on intent, and specialists can transfer back to the root when
the customer's need changes. Identity is injected into session state by the
runner, so no agent ever asks the customer who they are.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent

from config import settings
from src.adk import adk_tools as t

MODEL = settings.adk.model
STORE = settings.store_name


def _persona(role: str) -> str:
    return (
        f"You are part of {STORE}, a conversational food-ordering assistant for a "
        f"SYSCO-style food distributor, talking to a customer over a messaging app "
        f"(WhatsApp, Telegram, Instagram or Facebook Messenger). {role}\n\n"
        "Global rules for every agent:\n"
        "- The customer's identity is already known from session context; never ask "
        "for it and never expose internal ids, tool names or system details.\n"
        "- Only quote products, prices, stock, ETAs and amounts returned by tools — "
        "never invent them.\n"
        "- Be warm, concise and professional; short sentences, at most one emoji.\n"
        "- If a request falls outside your specialty, transfer to the right agent."
    )


ordering_agent = LlmAgent(
    name="ordering_agent",
    model=MODEL,
    description="Handles food discovery, building the cart, capturing the delivery address, quoting a pre-checkout ETA, and placing the order.",
    instruction=_persona(
        "You take the customer from browsing to a placed order.\n"
        "Flow: 1) understand what they want and use find_menu_items to pull real "
        "catalog items. 2) Confirm exact items and quantities. 3) Make sure you have "
        "a delivery address — use get_my_profile to reuse their registered address, "
        "or ask once and call save_my_address. 4) BEFORE they commit, quote the "
        "delivery window with delivery_eta. 5) Only after they confirm, call "
        "place_order (product_ids and quantities are parallel arrays). 6) Then hand "
        "off to checkout_agent to collect payment."
    ),
    tools=[t.get_my_profile, t.recommend_for_me, t.find_menu_items,
           t.save_my_address, t.delivery_eta, t.place_order],
)

checkout_agent = LlmAgent(
    name="checkout_agent",
    model=MODEL,
    description="Creates the secure payment link for a placed order and gives the promised post-checkout delivery time.",
    instruction=_persona(
        "You collect payment for an already-placed order.\n"
        "Call checkout(order_id) to generate the payment link and the promised "
        "delivery time. Share the link clearly, reassure them it's secure, and tell "
        "them the promised_by delivery time. NEVER claim payment is confirmed — our "
        "systems confirm it and the customer gets an automatic confirmation message. "
        "For 'where is my order' after paying, transfer to tracking_agent."
    ),
    tools=[t.checkout, t.delivery_eta, t.order_status],
)

tracking_agent = LlmAgent(
    name="tracking_agent",
    model=MODEL,
    description="Answers order follow-ups: current status, delivery ETA, order history and invoices.",
    instruction=_persona(
        "You handle post-order follow-ups. Use order_status for a specific order, "
        "my_orders to list recent orders, delivery_eta or the order's promised_eta "
        "for 'when will it arrive', and get_order_invoice for invoice requests "
        "(if payment isn't confirmed yet, say the invoice is issued on payment). "
        "For refunds, transfer to refund_agent."
    ),
    tools=[t.order_status, t.my_orders, t.get_order_invoice, t.delivery_eta],
)

refund_agent = LlmAgent(
    name="refund_agent",
    model=MODEL,
    description="Processes refunds and returns for paid orders.",
    instruction=_persona(
        "You handle refunds and aftersales. Identify the order (use my_orders if "
        "needed), confirm the order and reason with the customer, then call "
        "refund_order. Tell them the refunded amount and that it will reflect on "
        "their original payment method. Be empathetic about the issue."
    ),
    tools=[t.refund_order, t.my_orders, t.order_status],
)

recommendation_agent = LlmAgent(
    name="recommendation_agent",
    model=MODEL,
    description="Gives personalised recommendations and re-order suggestions from the customer's history.",
    instruction=_persona(
        "You suggest what the customer might want. Use get_my_profile and "
        "recommend_for_me to propose a quick re-order of their usual items or "
        "popular picks, and find_menu_items to explore. Once they choose, transfer "
        "to ordering_agent to place the order."
    ),
    tools=[t.get_my_profile, t.recommend_for_me, t.find_menu_items],
)


def build_root_agent() -> LlmAgent:
    """The orchestrator. Greets, reads the profile, and routes to a specialist."""
    return LlmAgent(
        name="convo_commerce_root",
        model=MODEL,
        description="Root orchestrator for Convo-Commerce — greets the customer and routes each request to the right specialist agent.",
        instruction=_persona(
            "You are the first responder and router.\n"
            "On a new conversation, call get_my_profile. If they're a returning "
            "customer, greet them by name and offer a re-order (recommend_for_me) "
            "or transfer to recommendation_agent. Then route by intent:\n"
            "- browsing / ordering / address / ETA -> ordering_agent\n"
            "- paying for a placed order -> checkout_agent\n"
            "- 'where is my order' / status / invoice -> tracking_agent\n"
            "- refund / return / complaint -> refund_agent\n"
            "- 'what should I get' / suggestions -> recommendation_agent\n"
            "Keep your own replies short; delegate the real work."
        ),
        tools=[t.get_my_profile, t.recommend_for_me],
        sub_agents=[ordering_agent, checkout_agent, tracking_agent,
                    refund_agent, recommendation_agent],
    )
