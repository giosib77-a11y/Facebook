-- ============================================================================
-- 0020: shops.instagram_account_id — partial UNIQUE ინდექსი (A-5 / B-9)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- `instagram_account_id` (0006) unique არ იყო. webhook IG შეტყობინებას მაღაზიას
-- ამ ID-ით პოულობს; თუ ერთი ID ორ მაღაზიაზეა, შეტყობინება შეიძლება სხვა
-- tenant-ის მაღაზიამ მიიღოს (მისი პროდუქტები, მისი ბოტი).
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- partial unique ინდექსი: ერთი IG ანგარიში — მაქსიმუმ ერთი მაღაზია (NULL-ები
-- არ ითვლება). backend-იც შეიცვალა: connect უარყოფს (reason=ig_taken) IG id-ს,
-- რომელიც უკვე სხვა მაღაზიაზეა, webhook კი ორაზროვან დამთხვევას არ ამუშავებს.
--
-- ⚠️ ჯერ გაუშვი PRE-CHECK. თუ რაიმე მწკრივი დაბრუნდა, ინდექსის შექმნა ჩავარდება —
--    ჯერ ხელით გადაწყვიტე, რომელ მაღაზიას რჩება IG ანგარიში, დანარჩენებზე
--    გაასუფთავე:  update public.shops set instagram_account_id = null where id = '<id>';
-- გაშვების რიგი: backend-ის deploy-ს არ ეყრდნობა (ახალი კოდი ინდექსის გარეშეც მუშაობს).
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (გაუშვი ცალკე, მიგრაციამდე). სწორი შედეგი: 0 მწკრივი.
--
--   select instagram_account_id, count(*) as shops, array_agg(id) as shop_ids
--   from public.shops
--   where instagram_account_id is not null
--   group by instagram_account_id
--   having count(*) > 1;
-- ----------------------------------------------------------------------------

begin;

create unique index if not exists shops_instagram_account_id_uniq
  on public.shops (instagram_account_id)
  where instagram_account_id is not null;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     (select count(*) from pg_indexes
--       where schemaname = 'public' and tablename = 'shops'
--         and indexname = 'shops_instagram_account_id_uniq'
--         and indexdef ilike '%unique%'
--         and indexdef ilike '%instagram_account_id is not null%')  as index_ok,
--     (select count(*) from (
--        select 1 from public.shops where instagram_account_id is not null
--        group by instagram_account_id having count(*) > 1) d)       as duplicates;
--
-- სწორი შედეგი: 1, 0
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK
--
-- ⚠️ ამის შემდეგ ერთი IG id ისევ შეიძლება რამდენიმე მაღაზიაზე აღმოჩნდეს
--    (backend მაინც არ დაარუტავს ორაზროვან შეტყობინებას — გამოტოვებს).
--
--   begin;
--   drop index if exists public.shops_instagram_account_id_uniq;
--   commit;
-- ----------------------------------------------------------------------------
