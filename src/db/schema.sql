-- ============================================================================
-- Conversational Commerce — Relational Schema
-- Target: SQLite (dev/demo) — column types are ANSI-compatible so the same
-- DDL ports cleanly to Postgres/MySQL with minimal changes.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Users: one row per customer, linked to a WhatsApp phone and/or Messenger id
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    phone_number   TEXT UNIQUE,              -- WhatsApp identity (E.164)
    messenger_id   TEXT UNIQUE,              -- Messenger PSID
    preferences    TEXT DEFAULT '{}',        -- JSON blob (favourite categories, sizes...)
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Products: the catalog
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    product_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    description    TEXT,
    price          REAL NOT NULL CHECK (price >= 0),
    currency       TEXT NOT NULL DEFAULT 'USD',
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    image_url      TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_name     ON products(name);

-- ---------------------------------------------------------------------------
-- Orders: one row per placed order line
-- status lifecycle: PENDING_PAYMENT -> PAID -> PACKED -> SHIPPED
--                   -> OUT_FOR_DELIVERY -> DELIVERED  (or CANCELLED / REFUNDED)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    order_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(user_id),
    product_id        INTEGER NOT NULL REFERENCES products(product_id),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    unit_price        REAL NOT NULL,          -- price captured at order time
    total_amount      REAL NOT NULL,
    currency          TEXT NOT NULL DEFAULT 'USD',
    status            TEXT NOT NULL DEFAULT 'PENDING_PAYMENT',
    payment_reference TEXT,                    -- gateway / WhatsApp Pay ref
    delivery_address  TEXT,
    tracking_number   TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_user   ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- ---------------------------------------------------------------------------
-- Messages: full conversation transcript, used for context + audit + the
-- WhatsApp 24-hour customer-service window calculation.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    message_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,                -- channel-scoped conversation id
    user_id     INTEGER REFERENCES users(user_id),
    channel     TEXT NOT NULL,                -- 'whatsapp' | 'messenger'
    direction   TEXT NOT NULL DEFAULT 'in',   -- 'in' (from user) | 'out' (from agent)
    content     TEXT NOT NULL,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);

-- ---------------------------------------------------------------------------
-- Order status history: event-driven tracking trail (drives notifications)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    status     TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id);
