-- ============================================================
-- 0007: ბოტის ენა (მრავალენოვნება)
-- auto = კლიენტის ენას მიჰყვება (ქართ./English), ka = მხოლოდ ქართული, en = English
-- გაუშვი Supabase → SQL Editor-ში.
-- ============================================================

alter table public.shops
  add column if not exists bot_language text not null default 'auto';

-- დასაშვები ენები: auto (კლიენტის ენა), ka (ქართული), en (English), ru (Русский)
alter table public.shops drop constraint if exists shops_bot_language_chk;
alter table public.shops
  add constraint shops_bot_language_chk check (bot_language in ('auto', 'ka', 'en', 'ru'));
