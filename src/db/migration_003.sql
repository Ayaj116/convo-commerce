-- ============================================================================
-- Migration 003 (Convo-Commerce): delivery addresses registered per customer.
--
-- The ETA engine (before & after checkout) works off the address registered
-- to a customer's profile, so we persist one or more addresses per customer
-- and flag a default. Run once in the Supabase SQL Editor. Idempotent.
-- ============================================================================

create table if not exists commerce.customer_addresses (
    id           uuid primary key default gen_random_uuid(),
    customer_id  uuid not null references commerce.customers(id) on delete cascade,
    label        text,                 -- 'Home', 'Office', ...
    address_line text not null,        -- full free-form delivery address
    city         text,
    postal_code  text,
    is_default   boolean not null default true,
    latitude     double precision,     -- optional; ETA falls back to a zone hash
    longitude    double precision,
    created_at   timestamptz not null default now()
);

create index if not exists idx_customer_addresses_customer
    on commerce.customer_addresses(customer_id);

-- Only one default address per customer.
create unique index if not exists uq_customer_addresses_default
    on commerce.customer_addresses(customer_id)
    where is_default;

-- Capture the promised delivery time on the order at checkout, so post-checkout
-- follow-ups can report the same ETA the customer was quoted.
alter table commerce.orders
    add column if not exists promised_eta timestamptz;
