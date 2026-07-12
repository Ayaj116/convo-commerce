"""
Convo-Commerce — tools/logic demo (NO LLM required).

Exercises the new food-delivery capabilities directly through the tool layer so
you can validate them without a model or API key — it only needs Supabase
(SUPABASE_URL / SUPABASE_SERVICE_KEY) and a seeded catalog:

    python scripts/seed_data.py
    python demo_tools.py

Flow: register a customer + delivery address -> pre-checkout ETA -> place a
multi-item order -> post-checkout (promised) ETA -> payment link -> confirm
payment (invoice) -> personalised recommendation from history -> refund.
"""
from __future__ import annotations

from config import settings
from src.tools import tools
from src.tools import eta as eta_engine


def _line(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    print(f"Convo-Commerce tools demo — {settings.store_name}\n")

    # --- ETA engine is pure: show it works with zero external services --------
    _line("ETA engine (pure, no DB)")
    for addr in ["200 Market St, San Francisco, 94103", "88 Rural Rd, 68001"]:
        est = eta_engine.compute_eta(addr)
        print(f"  {addr!r:45} -> {est['window_text']}  (by {est['promised_by']})")

    if not (settings.supabase.url and settings.supabase.service_key):
        print("\n(Set SUPABASE_URL / SUPABASE_SERVICE_KEY to run the full DB flow.)")
        return

    # --- Customer + registered address ---------------------------------------
    _line("Customer + registered address")
    profile = tools.ensure_customer_profile(
        channel="whatsapp", platform_user_id="+15550000001", display_name="Demo Diner")
    customer_id = profile["customer_id"]
    print(f"  customer_id = {customer_id}")
    addr = tools.save_customer_address(customer_id, "200 Market St, San Francisco, 94103",
                                       label="Restaurant", city="San Francisco", postal_code="94103")
    print(f"  saved address: {addr.get('address_line') or addr}")

    # --- Pre-checkout ETA (from registered address) --------------------------
    _line("Pre-checkout ETA (registered address)")
    print(f"  {tools.estimate_eta(customer_id=customer_id).get('window_text')}")

    # --- Discover + place a multi-item order ---------------------------------
    _line("Discover menu + place order")
    picks = tools.get_products_by_category_or_search(limit=2)
    if len(picks) < 1:
        print("  No products found — run scripts/seed_data.py first.")
        return
    items = [{"product_id": p["id"], "quantity": 2} for p in picks]
    for p in picks:
        print(f"  + {p['name']}  x2  @ {p['price']}")
    order = tools.create_order(customer_id, items,
                               delivery_address="200 Market St, San Francisco, 94103")
    if order.get("error"):
        print(f"  order error: {order}")
        return
    order_id = order["id"]
    print(f"  order {order['order_number']} total={order['total']} {order['currency']} status={order['status']}")

    # --- Post-checkout (promised) ETA ----------------------------------------
    _line("Post-checkout promised ETA")
    peta = tools.estimate_eta(order_id=order_id)
    print(f"  promised by {peta.get('promised_by')} (window {peta.get('window_text')})")

    # --- Payment link + confirm ----------------------------------------------
    _line("Payment link + confirmation")
    link = tools.create_payment_link(order_id, method="external")
    print(f"  pay: {link.get('url')}  (payment_id={link.get('payment_id')})")
    paid = tools.mark_payment_paid(link["payment_id"], payment_reference="DEMO-REF-1")
    print(f"  order status now: {paid['status']}")
    invoice = tools.get_invoice(order_id)
    print(f"  invoice: {invoice.get('invoice_number')} status={invoice.get('status')}")

    # --- Recommendation from history -----------------------------------------
    _line("Recommendation (from order history)")
    recs = tools.recommend_for_customer(customer_id)
    print(f"  returning_customer={recs['returning_customer']}")
    for r in recs["recommendations"]:
        print(f"  - {r['name']}  ({r['reason']})")

    # --- Refund ---------------------------------------------------------------
    _line("Refund")
    refund = tools.process_refund(order_id, reason="demo refund")
    print(f"  {refund}")


if __name__ == "__main__":
    main()
