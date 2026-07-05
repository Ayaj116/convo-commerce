"""
Database access layer (SQLite).

Thin wrapper around sqlite3 that:
  * returns dict-like rows,
  * enforces foreign keys,
  * initializes the schema on first use,
  * exposes a context manager for safe transactions.

Swapping to Postgres later means replacing this module + the driver; the
tool layer above only depends on get_conn()/query()/execute().
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from config import settings

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create tables if they do not exist."""
    path = db_path or settings.db_path
    ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
    with _connect(path) as conn:
        conn.executescript(ddl)
        conn.commit()


@contextmanager
def get_conn(db_path: str | None = None):
    """Transactional connection. Commits on success, rolls back on error."""
    path = db_path or settings.db_path
    if not os.path.exists(path):
        init_db(path)
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: Iterable[Any] = (), db_path: str | None = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: Iterable[Any] = (), db_path: str | None = None) -> dict | None:
    rows = query(sql, params, db_path)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = (), db_path: str | None = None) -> int:
    """Run an INSERT/UPDATE/DELETE. Returns lastrowid for inserts."""
    with get_conn(db_path) as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid
