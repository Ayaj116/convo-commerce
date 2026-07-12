"""
Delivery ETA engine — before and after checkout.

Food-delivery ETA has two moments the customer cares about:

  * BEFORE checkout — "how long will it take?" — an estimate *window* (e.g.
    "40–55 min") so they can decide whether to order.
  * AFTER  checkout — "when will it arrive?" — a *promised time* anchored to
    when the order was placed/paid (e.g. "by 7:52 PM").

Both are derived from the delivery address registered to the customer's
profile. There is no external maps dependency: travel time is a deterministic
function of the address's delivery zone (a stable hash of its postal
code / city), plus kitchen prep time, plus a peak-hour surcharge. Deterministic
means the same address always quotes the same window — demo-safe and testable —
while still varying believably block to block. Swap `_travel_minutes` for a real
routing/Distance-Matrix call in production without touching callers.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from config import settings


def _zone_key(address: str) -> str:
    """Reduce a free-form address to a stable delivery-zone key.

    Prefer a postal code if present (best proxy for a delivery zone); else fall
    back to the last comma-separated component (usually city/region); else the
    whole normalised string. Case/space-insensitive so trivial re-typings of the
    same address land in the same zone."""
    norm = " ".join(address.lower().split())
    # US 5-digit ZIP or generic 4-6 digit postal token.
    m = re.search(r"\b(\d{4,6})\b", norm)
    if m:
        return m.group(1)
    parts = [p.strip() for p in norm.split(",") if p.strip()]
    return parts[-1] if parts else norm


def _travel_minutes(address: str) -> tuple[int, int]:
    """Deterministic travel window (min, max) in minutes for an address zone."""
    d = settings.delivery
    lo, hi = d.min_travel_minutes, d.max_travel_minutes
    span = max(hi - lo, 1)
    digest = hashlib.sha256(_zone_key(address).encode()).hexdigest()
    base = lo + (int(digest[:8], 16) % span)          # deterministic center
    # A modest spread around the center gives the customer a believable window.
    spread = 5 + (int(digest[8:12], 16) % 8)          # 5–12 min
    return base, min(base + spread, hi + spread)


def _is_peak(when: datetime) -> bool:
    peak = {int(h) for h in settings.delivery.peak_hours.split(",") if h.strip().isdigit()}
    return when.hour in peak


def compute_eta(address: str | None, anchor: datetime | None = None) -> dict:
    """Compute an ETA for delivering to `address`.

    Returns both the estimate *window* (for pre-checkout) and, when `anchor`
    is given (order placed/paid time), a *promised* absolute arrival time (for
    post-checkout). All times are timezone-aware UTC ISO strings; the caller /
    channel formats them for the customer's locale.
    """
    if not address or not address.strip():
        return {
            "available": False,
            "reason": "no_address",
            "message": "Add a delivery address and I'll give you an exact ETA.",
        }

    when = anchor or datetime.now(timezone.utc)
    prep = settings.delivery.base_prep_minutes
    travel_lo, travel_hi = _travel_minutes(address)
    surcharge = settings.delivery.peak_surcharge_minutes if _is_peak(when) else 0

    min_minutes = prep + travel_lo + surcharge
    max_minutes = prep + travel_hi + surcharge
    promised_by = when + timedelta(minutes=max_minutes)

    return {
        "available": True,
        "address": address,
        "zone": _zone_key(address),
        "prep_minutes": prep,
        "travel_minutes": [travel_lo, travel_hi],
        "peak_surcharge_minutes": surcharge,
        "min_minutes": min_minutes,
        "max_minutes": max_minutes,
        # Human-friendly summary the agent can quote directly.
        "window_text": f"{min_minutes}–{max_minutes} min",
        "anchor": when.isoformat(),
        "promised_by": promised_by.isoformat(),
    }
