-- ============================================================================
-- One-time migration: run this in the Supabase SQL Editor before using the
-- Supabase-backed app. Adds columns the app needs that the original
-- `commerce` schema didn't have, plus two atomic stock-adjustment functions
-- (PostgREST alone can't do `SET x = x - 1` safely across two REST calls).
-- Safe to re-run (all statements are idempotent).
-- ============================================================================

alter table commerce.products
  add column if not exists category text,
  add column if not exists stock_quantity integer not null default 0;

alter table commerce.orders
  add column if not exists delivery_address text;

create index if not exists idx_products_category on commerce.products(category);

create or replace function commerce.decrement_stock(p_product_id uuid, p_qty integer)
returns setof commerce.products
language sql
as $$
  update commerce.products
  set stock_quantity = stock_quantity - p_qty
  where id = p_product_id and stock_quantity >= p_qty
  returning *;
$$;

create or replace function commerce.increment_stock(p_product_id uuid, p_qty integer)
returns setof commerce.products
language sql
as $$
  update commerce.products
  set stock_quantity = stock_quantity + p_qty
  where id = p_product_id
  returning *;
$$;

-- Migration 002: add 'telegram' as a supported channel alongside the
-- existing whatsapp/messenger/instagram values (confirmed via probing since
-- pg_get_constraintdef access wasn't available). Run in the SQL Editor.
alter table commerce.customer_profiles
  drop constraint if exists customer_profiles_channel_check;

alter table commerce.customer_profiles
  add constraint customer_profiles_channel_check
  check (channel = ANY (ARRAY['whatsapp'::character varying, 'messenger'::character varying,
                               'instagram'::character varying, 'telegram'::character varying]));
