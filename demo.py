"""
End-to-end demo — runs the full agent offline with the mock AI provider.

    python demo.py

Simulates a WhatsApp conversation (discovery -> order -> payment) and a
Messenger tracking query, then advances the order to show event-driven
tracking notifications. No API keys or network required.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Use a throwaway DB so the demo is repeatable.
os.environ.setdefault("DB_PATH", "demo.db")
os.environ.setdefault("AI_PROVIDER", "mock")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent.conversation import ConversationAgent
from src.agent.notifications import advance_and_notify
from src.db.database import init_db
from src.db.models import Channel, OrderStatus
from src.tools import tools
from scripts.seed_data import run as seed


def _reset() -> None:
    if os.path.exists("demo.db"):
        os.remove("demo.db")
    init_db()
    seed()


def _turn(agent: ConversationAgent, channel: str, sender: str, text: str, who="Customer"):
    print(f"\n  {who}: {text}")
    reply = agent.handle_message(channel, sender, text)
    print(f"  Agent: {reply}")


def main() -> None:
    _reset()
    agent = ConversationAgent()  # AI_PROVIDER=mock
    print("=" * 70)
    print(f"  Conversational Commerce Demo   (AI provider: {agent.provider.name})")
    print("=" * 70)

    wa = "15551234567"  # Priya, WhatsApp
    print("\n--- WhatsApp: discovery -> order -> payment ---")
    _turn(agent, Channel.WHATSAPP, wa, "Hi there!")
    _turn(agent, Channel.WHATSAPP, wa, "I want some running shoes")
    _turn(agent, Channel.WHATSAPP, wa, "I'll take 2 of the Aurora Runner Sneakers, ship to 12 Maple Street")

    # Find the order we just created and simulate fulfilment progress.
    user = tools.get_user_by_phone_or_profile_id(phone_number=wa)
    orders = tools.get_orders_for_user(user["user_id"])
    order_id = orders[0]["order_id"]
    print(f"\n--- Ops: mark PAID, then SHIP (event-driven notifications) ---")
    advance_and_notify(order_id, OrderStatus.PAID, "Payment settled")
    advance_and_notify(order_id, OrderStatus.SHIPPED, "Handed to courier")

    print("\n--- Messenger: tracking query ---")
    ms = "psid_998877"
    _turn(agent, Channel.MESSENGER, ms, "hello")
    _turn(agent, Channel.MESSENGER, ms, f"can you track order {order_id}?")

    print("\n--- Final order record ---")
    final = tools.get_order(order_id)
    print(f"  Order #{final['order_id']}: {final['product']['name']} x{final['quantity']} "
          f"= {final['currency']} {final['total_amount']:.2f} | status={final['status']}")
    print("  Status trail:", " -> ".join(e["status"] for e in final["events"]))
    print("\nDemo complete. ✅")


if __name__ == "__main__":
    main()
