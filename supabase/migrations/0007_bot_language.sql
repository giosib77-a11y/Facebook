-- ============================================================
-- 0007: ბოტის ენა (მრავალენოვნება)
-- auto = კლიენტის ენას მიჰყვება (ქართ./English), ka = მხოლოდ ქართული, en = English
-- გაუშვი Supabase → SQL Editor-ში.
-- ============================================================

alter table public.shops
  add column if not exists bot_language text not null default 'auto';
