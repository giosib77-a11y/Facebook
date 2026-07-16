-- ============================================================
-- 0006: Instagram-ის მხარდაჭერა
-- გამყიდვლის Facebook გვერდზე მიბმული Instagram Business ანგარიშის ID.
-- webhook ამით პოულობს მაღაზიას Instagram-ის შეტყობინებაზე.
-- გაუშვი Supabase → SQL Editor-ში.
-- ============================================================

alter table public.shops
  add column if not exists instagram_account_id text;

create index if not exists shops_instagram_account_idx
  on public.shops (instagram_account_id);
