"""
Offline unit tests for src/db/database.py's pure logic (filter-string
building, header/param construction, error handling). No network calls —
`requests` is mocked, so this runs with zero configuration.

Run:  python tests/test_database_wrapper.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")

from src.db import database as db  # noqa: E402


def test_filter_helpers():
    assert db.eq(True) == "eq.true"
    assert db.eq(False) == "eq.false"
    assert db.eq("abc") == "eq.abc"
    assert db.eq(5) == "eq.5"
    assert db.gte(5) == "gte.5"
    assert db.lte(5) == "lte.5"
    assert db.ilike("shoe") == "ilike.*shoe*"
    assert db.in_([1, 2, "x"]) == "in.(1,2,x)"
    print("ok: filter helpers")


def test_select_sends_correct_request():
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = [{"id": "1"}]
    with patch("requests.get", return_value=fake_response) as mock_get:
        rows = db.select("products", {"is_active": db.eq(True)}, order="price.asc", limit=5)
    assert rows == [{"id": "1"}]
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["is_active"] == "eq.true"
    assert kwargs["params"]["order"] == "price.asc"
    assert kwargs["params"]["limit"] == 5
    assert kwargs["headers"]["Accept-Profile"] == "commerce"
    assert kwargs["headers"]["apikey"] == "test-service-key"
    print("ok: select() builds correct params/headers")


def test_error_raises_database_error():
    fake_response = MagicMock(status_code=400)
    fake_response.json.return_value = {"message": "bad"}
    with patch("requests.get", return_value=fake_response):
        try:
            db.select("products")
        except db.DatabaseError as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("expected DatabaseError")
    print("ok: non-2xx raises DatabaseError")


def test_insert_uses_return_representation():
    fake_response = MagicMock(status_code=201)
    fake_response.json.return_value = [{"id": "new"}]
    with patch("requests.post", return_value=fake_response) as mock_post:
        row = db.insert_one("orders", {"total": 10})
    assert row == {"id": "new"}
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Prefer"] == "return=representation"
    print("ok: insert() requests return=representation")


def test_update_and_delete_require_filters():
    for fn in (db.update, db.delete):
        try:
            fn("products", {}, {}) if fn is db.update else fn("products", {})
        except ValueError:
            continue
        raise AssertionError(f"{fn.__name__} should refuse an empty filter")
    print("ok: update()/delete() refuse unfiltered mutations")


def test_rpc_posts_to_rpc_endpoint():
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = [{"id": "p1", "stock_quantity": 4}]
    with patch("requests.post", return_value=fake_response) as mock_post:
        rows = db.rpc("decrement_stock", {"p_product_id": "p1", "p_qty": 1})
    assert rows == [{"id": "p1", "stock_quantity": 4}]
    args, _ = mock_post.call_args
    assert args[0].endswith("/rpc/decrement_stock")
    print("ok: rpc() posts to the correct endpoint")


if __name__ == "__main__":
    test_filter_helpers()
    test_select_sends_correct_request()
    test_error_raises_database_error()
    test_insert_uses_return_representation()
    test_update_and_delete_require_filters()
    test_rpc_posts_to_rpc_endpoint()
    print("\nAll offline database wrapper tests passed.")
