-- ============================================================================
-- 0018: orders — სვეტის დონის ნებართვები, status CHECK, DELETE პოლისი (A-2)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- RLS პოლისები (0002) ამოწმებენ მწკრივს („ეს მაღაზია შენია?“), არა სვეტს, ხოლო
-- Supabase `authenticated`-ს ნაგულისხმევად აძლევს UPDATE/DELETE-ს მთელ ცხრილზე.
-- გამყიდველს საჯარო anon გასაღებით + საკუთარი JWT-ით შეეძლო პირდაპირ PostgREST-ზე:
--   PATCH  /rest/v1/orders?id=eq.<ჩემი>  {"items":[...], "total":...}
--     → items-ის გაბერვა და მერე API-ით „გაუქმება“ → მარაგის უკან დაბრუნება
--       (apply_stock_delta +1) რეალურზე მეტით = მარაგის გაბერვა;
--   PATCH  … {"status":"abc"}  → უცნობი სტატუსი (ბაზას არ ზღუდავდა);
--   DELETE /rest/v1/orders?id=eq.<ჩემი>  → აქტიური (new/processing) შეკვეთის
--     წაშლა, F-07-ის (მხოლოდ done/cancelled იშლება) გვერდის ავლით — processing
--     შეკვეთის მარაგი დაკლებულია და უკან აღარ დაბრუნდებოდა.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- 1) UPDATE-ს ვურთმევთ anon/authenticated-ს და authenticated-ს ვუბრუნებთ მხოლოდ
--    `status` სვეტზე. backend (orders.py update_order_status, auth.client) სწორედ
--    მხოლოდ `{"status": ...}`-ს წერს; `updated_at`-ს BEFORE UPDATE ტრიგერი
--    (set_updated_at, 0002) ავსებს — ტრიგერის მიერ NEW-ის შეცვლას სვეტის
--    ნებართვა არ სჭირდება, ამიტომ updated_at-ის grant საჭირო არაა.
--    (UPDATE ... WHERE status = ... ფილტრს SELECT სჭირდება — ის ხელუხლებელია.)
-- 2) CHECK: status in ('new','processing','done','cancelled') — იგივე ოთხი,
--    რასაც backend (OrderStatusUpdate Literal), INSERT ('new') და frontend იყენებს.
-- 3) DELETE პოლისი ისე იცვლება, რომ გამყიდველმა წაშალოს მხოლოდ საკუთარი
--    მაღაზიის `done`/`cancelled` შეკვეთა. DELETE ნებართვა authenticated-ზე რჩება,
--    რადგან backend (orders.py delete_order) შეკვეთას auth.client-ით (RLS) შლის.
--    anon-ს DELETE ეხსნება (არც პოლისი ჰქონდა, არც საჭიროა).
-- INSERT ყოველთვის service_role-ით ხდება (public create_order); service_role-ის
-- უფლებები და admin delete (service_role; shops CASCADE) ხელუხლებელია.
--
-- ⚠️ ჯერ გაუშვი PRE-CHECK. თუ რიცხვი > 0, CHECK ჩავარდება — ჯერ ის მწკრივები
--    გაასწორე.
-- გაშვების რიგი: backend-ის deploy-ს არ ეყრდნობა (კოდი უკვე მხოლოდ status-ს წერს
-- და done/cancelled-ს შლის) — შეიძლება ნებისმიერ დროს.
--
-- ⚠️ რიგი მნიშვნელოვანია: ცხრილის დონის REVOKE სვეტის დონის ნებართვებსაც
--    აუქმებს, ამიტომ ჯერ revoke, მერე column grant. ასე იდემპოტენტურიცაა.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (გაუშვი ცალკე, მიგრაციამდე). სწორი შედეგი: 0 მწკრივი.
--
--   select status, count(*) from public.orders
--   where status is null
--      or status not in ('new','processing','done','cancelled')
--   group by status;
-- ----------------------------------------------------------------------------

begin;

revoke update on public.orders from anon, authenticated;
grant update (status) on public.orders to authenticated;

revoke delete on public.orders from anon;

alter table public.orders drop constraint if exists orders_status_chk;
alter table public.orders add constraint orders_status_chk
  check (status in ('new', 'processing', 'done', 'cancelled')) not valid;
alter table public.orders validate constraint orders_status_chk;

drop policy if exists "orders_delete_own" on public.orders;
create policy "orders_delete_own"
    on public.orders for delete
    using (
        status in ('done', 'cancelled')
        and exists (
            select 1 from public.shops s
            where s.id = orders.shop_id and s.owner_id = auth.uid()
        )
    );

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     has_column_privilege('authenticated','public.orders','status','UPDATE')     as status_upd,
--     has_column_privilege('authenticated','public.orders','items','UPDATE')      as items_upd,
--     has_column_privilege('authenticated','public.orders','total','UPDATE')      as total_upd,
--     has_column_privilege('authenticated','public.orders','shop_id','UPDATE')    as shop_upd,
--     has_table_privilege('anon','public.orders','UPDATE')                        as anon_upd,
--     has_table_privilege('anon','public.orders','DELETE')                        as anon_del,
--     has_table_privilege('authenticated','public.orders','DELETE')               as auth_del,
--     has_table_privilege('service_role','public.orders','UPDATE')                as svc_upd,
--     (select count(*) from pg_constraint
--       where conrelid = 'public.orders'::regclass and conname = 'orders_status_chk'
--         and convalidated)                                                       as chk_valid,
--     (select pg_get_expr(polqual, polrelid) like '%done%'
--       from pg_policy where polrelid = 'public.orders'::regclass
--         and polname = 'orders_delete_own')                                      as del_policy_has_status;
--
-- სწორი შედეგი: t, f, f, f, f, f, t, t, 1, t
--
-- ხელით შემოწმება (გამყიდველის ანგარიშით): პანელში სტატუსის შეცვლა და
-- done/cancelled შეკვეთის წაშლა მუშაობს; new/processing-ის წაშლა → 409.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK
--
-- ⚠️ ამის შემდეგ ზემოთ აღწერილი ხვრელები ისევ ღიაა (items/total პირდაპირ
--    შეცვლა, აქტიური შეკვეთის პირდაპირ წაშლა). backend-ის კოდს rollback არ
--    სჭირდება.
--
--   begin;
--   grant update on public.orders to authenticated;
--   grant delete on public.orders to anon;  -- არასავალდებულო (RLS ისედაც ზღუდავდა)
--   alter table public.orders drop constraint if exists orders_status_chk;
--   drop policy if exists "orders_delete_own" on public.orders;
--   create policy "orders_delete_own"
--       on public.orders for delete
--       using (
--           exists (
--               select 1 from public.shops s
--               where s.id = orders.shop_id and s.owner_id = auth.uid()
--           )
--       );
--   commit;
-- ----------------------------------------------------------------------------
