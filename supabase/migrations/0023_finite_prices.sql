-- 0023: reject NaN / Infinity in money columns.
-- In Postgres NaN sorts above every number, so the existing `price >= 0` /
-- `total >= 0` checks accept 'NaN'. `< 'Infinity'` excludes both NaN and Infinity.
-- Idempotent. Run manually in the Supabase SQL Editor.

-- PRE-CHECK (expect 0 and 0; if not, fix those rows first or the ALTER fails):
--   select count(*) from public.products where price >= 'Infinity';
--   select count(*) from public.orders   where total >= 'Infinity';

alter table public.products drop constraint if exists products_price_finite_check;
alter table public.products
    add constraint products_price_finite_check check (price < 'Infinity');

alter table public.orders drop constraint if exists orders_total_finite_check;
alter table public.orders
    add constraint orders_total_finite_check check (total < 'Infinity');

-- VERIFY (expect 2 rows):
--   select conname from pg_constraint
--   where conname in ('products_price_finite_check', 'orders_total_finite_check');
