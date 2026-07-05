"""Seed the database with a demo catalog and a sample customer."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.database import init_db
from src.tools import tools

CATALOG = [
    ("Aurora Runner Sneakers", "Footwear", "Lightweight everyday running shoes", 79.99, 40),
    ("Trailblazer Hiking Boots", "Footwear", "Waterproof boots for rough terrain", 129.99, 15),
    ("Classic Canvas Slip-ons", "Footwear", "Casual canvas shoes, all-day comfort", 44.99, 0),
    ("Cloudstep Sandals", "Footwear", "Cushioned summer sandals", 34.99, 60),
    ("Metro Leather Jacket", "Apparel", "Genuine leather biker jacket", 199.99, 12),
    ("Everyday Cotton Tee", "Apparel", "Soft breathable crew-neck t-shirt", 19.99, 200),
    ("Summit Down Vest", "Apparel", "Packable insulated vest", 89.99, 25),
    ("Nomad Backpack 30L", "Accessories", "Durable travel & daypack", 64.99, 35),
    ("Horizon Sunglasses", "Accessories", "Polarized UV400 sunglasses", 49.99, 80),
    ("PowerCore 20k Charger", "Electronics", "20,000mAh fast-charge power bank", 39.99, 50),
]


def run() -> None:
    init_db()
    for name, cat, desc, price, stock in CATALOG:
        existing = tools.get_products_by_category_or_search(query=name)
        if not existing:
            from src.db import database as db
            db.execute(
                "INSERT INTO products (name, category, description, price, stock_quantity) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, cat, desc, price, stock),
            )
    # A sample WhatsApp customer.
    if not tools.get_user_by_phone_or_profile_id(phone_number="15551234567"):
        tools.create_user(name="Priya", phone_number="15551234567")
    print("Seeded catalog with", len(CATALOG), "products and 1 sample customer.")


if __name__ == "__main__":
    run()
