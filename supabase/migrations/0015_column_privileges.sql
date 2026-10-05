-- ============================================================================
-- 0015: სვეტის დონის ნებართვები shops / products-ზე (უსაფრთხოება)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- RLS პოლისები (0001) ამოწმებენ **მწკრივს** („ეს მაღაზია შენია?“), არა **სვეტს**.
-- Supabase კი `authenticated`-ს ნაგულისხმევად აძლევს INSERT/UPDATE-ს მთელ ცხრილზე.
-- შედეგად გამყიდველს საჯარო anon გასაღებით + საკუთარი JWT-ით შეეძლო პირდაპირ
-- PostgREST-ზე (/rest/v1/shops) ჩაეწერა ნებისმიერ სვეტში თავის მწკრივზე.
--
-- ᲗᲐᲕᲓᲐᲡᲮᲛᲐ
--   PATCH /rest/v1/shops?id=eq.<ჩემი>  {"subscription_tier":"business"}
--     → ფასიანი პაკეტი გადახდის გარეშე (Excel/PDF, ლიმიტები)
--   PATCH … {"bot_enabled":true}  → downgrade-ის შემდეგ გათიშული ბოტის ჩართვა
--   PATCH … {"facebook_page_id":"<სხვისი გვერდი>"} / instagram_account_id
--     → სხვისი გვერდის „დაკავება“ (squatting) — webhook მის შეტყობინებებს
--       ჩვენს მაღაზიას მიაბამდა
--   POST /rest/v1/shops / products → მაღაზიების/პროდუქტების ლიმიტის გვერდის ავლა
--
-- ⚠️ ჩვენი backend-ის შემოწმებები (ლიმიტი, პაკეტი) ამას ვერ ხედავს — მოთხოვნა
--    პირდაპირ Supabase-ს მიდის.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- INSERT/UPDATE-ს ვურთმევთ anon/authenticated-ს და UPDATE-ს ვუბრუნებთ მხოლოდ
-- უსაფრთხო სვეტებზე. პრივილეგირებულ ჩაწერას (owner_id, subscription_tier,
-- bot_enabled, facebook_*, instagram_account_id) და ყველა INSERT-ს backend
-- აკეთებს service_role-ით, მფლობელობის შემოწმების შემდეგ:
--   shops.py     create_shop / downgrade_to_free   (get_service_client)
--   facebook.py  disconnect                        (get_service_client)
--   products.py  create_product / import_products  (get_service_client)
--
-- SELECT / DELETE ნებართვები და RLS პოლისები ხელუხლებელია.
-- `knowledge` გამყიდვლისთვის ჩაწერადი რჩება — მიღებული ნარჩენი რისკი.
--
-- ⚠️ რიგი მნიშვნელოვანია: ცხრილის დონის REVOKE სვეტის დონის ნებართვებსაც
--    აუქმებს, ამიტომ ჯერ revoke, მერე column grant. ასე იდემპოტენტურიცაა.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

begin;

revoke insert, update on public.shops from anon, authenticated;
grant update (name, description, currency, bot_language, knowledge, knowledge_filename)
  on public.shops to authenticated;

revoke insert, update on public.products from anon, authenticated;
grant update (name, description, sku, price, quantity, image_url, is_active)
  on public.products to authenticated;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     has_table_privilege('authenticated','public.shops','INSERT')                       as shops_insert,
--     has_column_privilege('authenticated','public.shops','subscription_tier','UPDATE')  as tier_upd,
--     has_column_privilege('authenticated','public.shops','bot_enabled','UPDATE')        as bot_upd,
--     has_column_privilege('authenticated','public.shops','facebook_page_id','UPDATE')   as page_upd,
--     has_column_privilege('authenticated','public.shops','instagram_account_id','UPDATE') as ig_upd,
--     has_column_privilege('authenticated','public.shops','bot_language','UPDATE')       as lang_upd,
--     has_table_privilege('authenticated','public.products','INSERT')                    as prod_insert,
--     has_column_privilege('authenticated','public.products','shop_id','UPDATE')         as prod_shop_upd,
--     has_column_privilege('authenticated','public.products','price','UPDATE')           as prod_price_upd;
--
-- სწორი შედეგი: f, f, f, f, f, t, f, f, t
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK (Supabase-ის ნაგულისხმევ ნებართვებზე დაბრუნება)
--
-- ⚠️ ამის შემდეგ ზემოთ აღწერილი ხვრელი ისევ ღიაა. backend-ის კოდს rollback
--    არ სჭირდება — service_role ორივე შემთხვევაში მუშაობს.
--
--   begin;
--   grant insert, update on public.shops    to anon, authenticated;
--   grant insert, update on public.products to anon, authenticated;
--   commit;
-- ----------------------------------------------------------------------------
