"""
Seed the Supabase `commerce.products` table with the Convo-Commerce demo food
catalog (SYSCO-style food distribution).

Idempotent — matches existing rows by name, so re-running never creates
duplicates against the live (shared) Supabase project.

    python scripts/seed_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import database as db
from src.db.database import init_db

# A SYSCO-style foodservice catalog: proteins, produce, dairy, bakery, pantry,
# beverages — the kind of line items a restaurant or kitchen re-orders.
CATALOG = [
    # name, sku, category, description, price, stock_quantity
    ("Fresh Chicken Breast (case, 40 lb)", "PRO-CHK-001", "Proteins", "Boneless skinless, individually quick-frozen", 89.99, 60),
    ("Ground Beef 80/20 (case, 40 lb)", "PRO-BEF-002", "Proteins", "Fresh coarse-ground chuck", 129.99, 45),
    ("Atlantic Salmon Fillet (case, 20 lb)", "PRO-SAL-003", "Proteins", "Skin-on, portion-cut", 179.99, 20),
    ("Roma Tomatoes (case, 25 lb)", "PRD-TOM-001", "Produce", "Firm, vine-ripened", 24.99, 80),
    ("Romaine Lettuce (case, 24 ct)", "PRD-LET-002", "Produce", "Crisp hearts, washed", 27.50, 0),
    ("Yellow Onions (sack, 50 lb)", "PRD-ONI-003", "Produce", "Jumbo cooking onions", 19.99, 100),
    ("Shredded Mozzarella (case, 4x5 lb)", "DAI-MOZ-001", "Dairy", "Low-moisture, part-skim", 74.99, 50),
    ("Large Eggs (case, 15 dozen)", "DAI-EGG-002", "Dairy", "Grade A, USDA", 42.99, 70),
    ("Salted Butter (case, 36x1 lb)", "DAI-BUT-003", "Dairy", "AA-grade, foodservice", 118.00, 30),
    ("Burger Buns (case, 96 ct)", "BAK-BUN-001", "Bakery", "Sesame, sliced", 21.99, 90),
    ("Ciabatta Rolls (case, 48 ct)", "BAK-CIA-002", "Bakery", "Par-baked, artisan", 26.99, 40),
    ("Extra-Virgin Olive Oil (case, 4x1 gal)", "PAN-OIL-001", "Pantry", "Cold-pressed, foodservice", 96.00, 35),
    ("All-Purpose Flour (bag, 50 lb)", "PAN-FLR-002", "Pantry", "Enriched, unbleached", 23.50, 65),
    ("Marinara Sauce (case, 6 #10 cans)", "PAN-MAR-003", "Pantry", "Slow-simmered, no added sugar", 39.99, 55),
    ("Cola Syrup BiB (5 gal)", "BEV-COL-001", "Beverages", "Bag-in-box fountain syrup", 84.99, 25),
    ("Bottled Spring Water (case, 24x500ml)", "BEV-WAT-002", "Beverages", "Natural spring water", 8.99, 200),
]


def run() -> None:
    init_db()
    created = 0
    for name, sku, category, description, price, stock in CATALOG:
        if db.select_one("products", {"name": db.eq(name)}):
            continue
        db.insert_one("products", {
            "name": name,
            "sku": sku,
            "category": category,
            "description": description,
            "price": price,
            "stock_quantity": stock,
            "is_active": True,
        })
        created += 1
    print(f"Seeded SYSCO food catalog: {created} new product(s) added "
          f"({len(CATALOG) - created} already present).")


if __name__ == "__main__":
    run()
