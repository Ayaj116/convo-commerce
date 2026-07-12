"""
Database access layer — Supabase Postgres via PostgREST (HTTPS REST, port 443).

Thin wrapper around `requests` against the `commerce` schema. There is no raw
SQL here — callers pass table names, PostgREST-style filters, and plain dicts.
Writes always use the service_role key (server-side only) so they bypass RLS;
never expose SUPABASE_SERVICE_KEY to a client-facing surface.

Filters are dicts of {column: "operator.value"}, e.g. {"id": eq(order_id)}.
Use the eq/neq/gte/lte/ilike/in_ helpers below to build filter values — they
also convert Python bool -> lowercase "true"/"false", which PostgREST
requires and plain str()/f-strings get wrong (str(True) == "True").
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import requests

from config import settings

log = logging.getLogger("db")

_TIMEOUT = 10


class DatabaseError(RuntimeError):
    def __init__(self, table: str, op: str, response: requests.Response) -> None:
        self.table = table
        self.op = op
        self.status_code = response.status_code
        try:
            self.detail = response.json()
        except ValueError:
            self.detail = response.text
        super().__init__(f"{op} on {table} failed ({response.status_code}): {self.detail}")


# ---------------------------------------------------------------------------
# Filter-value helpers
# ---------------------------------------------------------------------------
def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def eq(value: Any) -> str:
    return f"eq.{_fmt(value)}"


def neq(value: Any) -> str:
    return f"neq.{_fmt(value)}"


def gte(value: Any) -> str:
    return f"gte.{_fmt(value)}"


def lte(value: Any) -> str:
    return f"lte.{_fmt(value)}"


def ilike(value: Any) -> str:
    return f"ilike.*{value}*"


def in_(values: Iterable[Any]) -> str:
    return "in.(" + ",".join(_fmt(v) for v in values) + ")"


# ---------------------------------------------------------------------------
# Connection plumbing
# ---------------------------------------------------------------------------
def _base_url() -> str:
    url = (settings.supabase.url or "").strip().rstrip("/")
    if not url:
        raise RuntimeError("SUPABASE_URL must be set in .env")
    return f"{url}/rest/v1"


def _headers(prefer: str | None = None) -> dict:
    key = (settings.supabase.service_key or "").strip()
    if not key:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY must be set in .env (server-side service_role secret key)"
        )
    schema = settings.supabase.schema
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept-Profile": schema,
        "Content-Profile": schema,
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def init_db(*_args, **_kwargs) -> None:
    """Startup health check — fails fast on misconfiguration instead of on
    the first real customer message."""
    select("products", limit=1)
    log.info("Supabase connectivity OK (schema=%s)", settings.supabase.schema)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def select(
    table: str,
    filters: dict[str, str] | None = None,
    columns: str = "*",
    order: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    params: dict[str, Any] = {"select": columns}
    params.update(filters or {})
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = limit
    r = requests.get(f"{_base_url()}/{table}", headers=_headers(), params=params, timeout=_TIMEOUT)
    if r.status_code >= 400:
        raise DatabaseError(table, "select", r)
    return r.json()


def select_one(table: str, filters: dict[str, str], columns: str = "*") -> dict | None:
    rows = select(table, filters, columns=columns, limit=1)
    return rows[0] if rows else None


def insert(table: str, data: dict | list[dict]) -> list[dict]:
    r = requests.post(
        f"{_base_url()}/{table}",
        headers=_headers(prefer="return=representation"),
        json=data,
        timeout=_TIMEOUT,
    )
    if r.status_code >= 400:
        raise DatabaseError(table, "insert", r)
    return r.json()


def insert_one(table: str, data: dict) -> dict:
    return insert(table, data)[0]


def update(table: str, filters: dict[str, str], data: dict) -> list[dict]:
    if not filters:
        raise ValueError(f"refusing to update every row of {table} with no filters")
    r = requests.patch(
        f"{_base_url()}/{table}",
        headers=_headers(prefer="return=representation"),
        params=filters,
        json=data,
        timeout=_TIMEOUT,
    )
    if r.status_code >= 400:
        raise DatabaseError(table, "update", r)
    return r.json()


def delete(table: str, filters: dict[str, str]) -> list[dict]:
    if not filters:
        raise ValueError(f"refusing to delete every row of {table} with no filters")
    r = requests.delete(
        f"{_base_url()}/{table}",
        headers=_headers(prefer="return=representation"),
        params=filters,
        timeout=_TIMEOUT,
    )
    if r.status_code >= 400:
        raise DatabaseError(table, "delete", r)
    return r.json()


def rpc(name: str, params: dict | None = None) -> list[dict]:
    """Call a Postgres function exposed in the commerce schema (e.g. the
    decrement_stock/increment_stock functions from migration_001.sql)."""
    r = requests.post(
        f"{_base_url()}/rpc/{name}",
        headers=_headers(prefer="return=representation"),
        json=params or {},
        timeout=_TIMEOUT,
    )
    if r.status_code >= 400:
        raise DatabaseError(f"rpc/{name}", "rpc", r)
    data = r.json()
    return data if isinstance(data, list) else [data]
