-- ============================================================================
-- 0024: upgrade_requests — INSERT მოხსნილია authenticated-დან; ერთი pending მაღაზიაზე (S12-3)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- ur_owner_insert (0005/0019) გამყიდველს PostgREST-ით პირდაპირ წერის უფლებას აძლევდა.
-- policy მხოლოდ მნიშვნელობებს ამოწმებს, რაოდენობას და created_at-ს — არა:
--   POST /rest/v1/upgrade_requests  [ათასობით {"shop_id":"<ჩემი>","requested_tier":"basic"}, ...]
-- → ბაზა უსაზღვროდ იზრდება (Supabase Free-ზე ლიმიტის გადაცდენისას ჩაწერა წყდება),
--   ადმინის pending-სია ყალბი მწკრივებით ივსება (მომავალი created_at-ით სიის თავში).
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- 1) revoke insert/update/delete from anon, authenticated; ur_owner_insert policy იშლება.
--    backend (shops.py request_upgrade) ჩაწერს service client-ით, მფლობელობის RLS-ით
--    შემოწმების შემდეგ + rate limit. SELECT (ur_owner_select) ხელუხლებელია.
-- 2) partial unique index: მაღაზიაზე მაქს. ერთი pending. backend ახალი მოთხოვნისას
--    მფლობელის ყველა მაღაზიის ძველ pending-ს ჯერ აუქმებს (per-account), ამიტომ თავსებადია.
--
-- ⚠️ გაშვების რიგი (RUN ORDER):
--    1. ჯერ backend-ის DEPLOY (ახალი request_upgrade service client-ით წერს);
--    2. PRE-CHECK;
--    3. ეს მიგრაცია;
--    4. ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (ქვემოთ).
--    ძველი backend + 0024 = „პაკეტის მოთხოვნა" 403/500.
--
-- ⚠️ ცხრილის REVOKE სვეტის ნებართვებსაც აუქმებს. იდემპოტენტურია.
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (ინფორმაციული; unique index-ს ხელს უშლის, თუ რამე დაბრუნდა — მიგრაცია
-- ქვემოთ დუბლიკატ pending-ებს თავადვე „cancelled"-ზე გადაიყვანს, ახალს ტოვებს):
--
--   select shop_id, count(*) from public.upgrade_requests
--   where status = 'pending' group by shop_id having count(*) > 1;
-- ----------------------------------------------------------------------------

begin;

revoke insert, update, delete on public.upgrade_requests from anon, authenticated;
drop policy if exists "ur_owner_insert" on public.upgrade_requests;

-- დუბლიკატი pending-ები: თითო მაღაზიაზე ყველაზე ახალი რჩება
update public.upgrade_requests u
set status = 'cancelled'
where u.status = 'pending'
  and exists (
    select 1 from public.upgrade_requests n
    where n.shop_id = u.shop_id and n.status = 'pending'
      and (n.created_at, n.id) > (u.created_at, u.id)
  );

create unique index if not exists upgrade_requests_one_pending_idx
  on public.upgrade_requests (shop_id) where status = 'pending';

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     has_table_privilege('authenticated','public.upgrade_requests','INSERT')  as auth_insert,   -- false
--     has_table_privilege('authenticated','public.upgrade_requests','SELECT')  as auth_select,   -- true
--     has_table_privilege('anon','public.upgrade_requests','INSERT')           as anon_insert,   -- false
--     (select count(*) from pg_policies
--       where schemaname='public' and tablename='upgrade_requests'
--         and policyname='ur_owner_insert')                                    as insert_policies, -- 0
--     (select count(*) from pg_indexes
--       where indexname='upgrade_requests_one_pending_idx')                    as unique_idx;      -- 1
--
-- სწორი შედეგი: f, t, f, 0, 1.
-- ხელით: პანელში პაკეტის მოთხოვნა მუშაობს (200); ადმინში pending ჩანს.
--
-- ROLLBACK:
--   begin;
--   drop index if exists public.upgrade_requests_one_pending_idx;
--   grant insert on public.upgrade_requests to authenticated;
--   -- + 0019-ის ur_owner_insert policy ხელახლა
--   commit;
-- ============================================================================
