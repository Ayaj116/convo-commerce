"""
Convo-Commerce — ADK multi-agent demo.

Drives a scripted WhatsApp conversation through the Google ADK multi-agent
system end to end: greet a returning customer, recommend a re-order, quote a
pre-checkout ETA, place an order, create a payment link with a promised
delivery time, then confirm payment (which fires the real-time cross-channel
confirmation) and show the invoice.

Requirements to run the LLM path:
  * pip install -r requirements.txt   (google-adk)
  * a valid GOOGLE_API_KEY in .env    (ADK_MODEL defaults to gemini-2.0-flash)
  * SUPABASE_URL / SUPABASE_SERVICE_KEY, and `python scripts/seed_data.py` once

If google-adk or the key isn't available, this prints setup guidance instead of
failing. For a no-LLM validation of the tools/ETA/refund logic, run
`python demo_tools.py`.
"""
from __future__ import annotations

from config import settings

CHANNEL = "whatsapp"
SENDER = "+15551234567"   # demo WhatsApp number (also the platform_user_id)
NAME = "Maria's Kitchen"

SCRIPT = [
    "Hi! This is Maria's Kitchen, I'd like to reorder for the week.",
    "Yes, my usual — and add a case of Roma Tomatoes. Deliver to 200 Market St, 94103.",
    "How long will delivery take?",
    "Great, please place the order and send me the payment link.",
]


def main() -> None:
    if settings.agent_engine != "adk":
        print("Set AGENT_ENGINE=adk in .env to run the multi-agent demo.")
        return
    try:
        from src.adk import runner
    except Exception as exc:  # noqa: BLE001
        print(f"google-adk not importable ({exc}).\nRun: pip install -r requirements.txt")
        return
    if not runner.is_available():
        print("ADK engine unavailable. Check GOOGLE_API_KEY in .env and that "
              "google-adk is installed.")
        return

    print(f"=== Convo-Commerce ({settings.store_name}) — ADK multi-agent demo ===\n")
    for turn in SCRIPT:
        print(f"[{NAME} -> {CHANNEL}]  {turn}")
        reply = runner.handle_message(CHANNEL, SENDER, turn, name=NAME)
        print(f"[Convo-Commerce]  {reply}\n")

    print("--- Next: confirm payment out-of-band to trigger the real-time "
          "confirmation ---")
    print("Find the pending payment id (get it from the order) and POST to:")
    print("  /payments/{payment_id}/confirm   (ops endpoint, X-Ops-Key header)")
    print("That marks the order PAID, issues the invoice, and messages the "
          "customer their delivery ETA automatically.")


if __name__ == "__main__":
    main()
