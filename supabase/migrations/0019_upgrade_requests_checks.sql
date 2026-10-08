-- ============================================================================
-- 0019: upgrade_requests — INSERT პოლისის გამკაცრება + status/tier CHECK (A-3)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- `ur_owner_insert` (0005) მხოლოდ მაღაზიის მფლობელობას ამოწმებდა, სვეტებს — არა.
-- გამყიდველს საჯარო anon გასაღებით + საკუთარი JWT-ით შეეძლო პირდაპირ PostgREST-ზე:
--   POST /rest/v1/upgrade_requests
--        {"shop_id":"<ჩემი>","requested_tier":"business","status":"approved",
--         "resolved_at":"2026-01-01T00:00:00Z"}
--   → თავისი თავის „დადასტურებულ“ მოთხოვნად გამოცხადება, ან უცნობი tier/status
--     (ბაზას არც requested_tier, არც status არ ზღუდავდა) — ადმინის სიაში
--     (status = 'pending') ნაგავი/არასწორი მწკრივები.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- 1) `ur_owner_insert` WITH CHECK-ს დაემატა:
--      status = 'pending' and resolved_at is null
--      and requested_tier in ('basic','standard','business')
--    + მფლობელობის exists() (უცვლელი). 'free' არ შედის — backend (request_upgrade)
--    „free“-ს ისედაც 400-ით აბრუნებს (TIER_LABELS-იდან, backend/app/core/tiers.py).
-- 2) CHECK-ები ცხრილზე (service_role-საც ეხება):
--      status in ('pending','approved','rejected','cancelled')
--      requested_tier in ('basic','standard','business')
--    ⚠️ 'cancelled' შეგნებულად შედის: backend (shops.py _cancel_pending_requests
--    და downgrade-free) ძველ pending მოთხოვნებს `status = 'cancelled'`-ზე
--    გადაჰყავს service_role-ით. მის გარეშე CHECK ამ UPDATE-ს ჩააგდებდა, ხოლო
--    try/except ჩუმად შთანთქავდა → ერთ მაღაზიაზე რამდენიმე pending დარჩებოდა.
--
-- BACKEND-ის თავსებადობა (კოდი არ იცვლება):
--   * request_upgrade: auth.client-ით (მომხმარებლის JWT, RLS) ჩასვამს ზუსტად
--     {shop_id, requested_tier ∈ basic|standard|business, status:'pending'};
--     resolved_at არ იგზავნება (NULL) → ახალ WITH CHECK-ს აკმაყოფილებს.
--   * admin approve/reject: service_role-ით UPDATE status ∈ approved|rejected
--     + resolved_at → CHECK-ს აკმაყოფილებს (RLS-ს გვერდს უვლის).
--
-- ⚠️ ჯერ გაუშვი PRE-CHECK. თუ რაიმე მწკრივი დაბრუნდა, VALIDATE ჩავარდება — ჯერ
--    ის მწკრივები გაასწორე.
-- გაშვების რიგი: backend-ის deploy-ს არ ეყრდნობა — შეიძლება ნებისმიერ დროს.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (გაუშვი ცალკე, მიგრაციამდე). სწორი შედეგი: 0 მწკრივი.
--
--   select id, status, requested_tier from public.upgrade_requests
--   where status is null
--      or status not in ('pending','approved','rejected','cancelled')
--      or requested_tier is null
--      or requested_tier not in ('basic','standard','business');
-- ----------------------------------------------------------------------------

begin;

alter table public.upgrade_requests drop constraint if exists upgrade_requests_status_chk;
alter table public.upgrade_requests add constraint upgrade_requests_status_chk
  check (status in ('pending', 'approved', 'rejected', 'cancelled')) not valid;
alter table public.upgrade_requests validate constraint upgrade_requests_status_chk;

alter table public.upgrade_requests drop constraint if exists upgrade_requests_tier_chk;
alter table public.upgrade_requests add constraint upgrade_requests_tier_chk
  check (requested_tier in ('basic', 'standard', 'business')) not valid;
alter table public.upgrade_requests validate constraint upgrade_requests_tier_chk;

drop policy if exists "ur_owner_insert" on public.upgrade_requests;
create policy "ur_owner_insert" on public.upgrade_requests
  for insert with check (
    status = 'pending'
    and resolved_at is null
    and requested_tier in ('basic', 'standard', 'business')
    and exists (select 1 from public.shops s
                where s.id = upgrade_requests.shop_id and s.owner_id = auth.uid())
  );

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     (select count(*) from pg_constraint
--       where conrelid = 'public.upgrade_requests'::regclass
--         and conname in ('upgrade_requests_status_chk','upgrade_requests_tier_chk')
--         and convalidated)                                                     as chk_valid,
--     (select pg_get_expr(polwithcheck, polrelid) like '%pending%'
--         and pg_get_expr(polwithcheck, polrelid) like '%resolved_at%'
--         and pg_get_expr(polwithcheck, polrelid) like '%business%'
--       from pg_policy where polrelid = 'public.upgrade_requests'::regclass
--         and polname = 'ur_owner_insert')                                      as insert_policy_ok;
--
-- სწორი შედეგი: 2, t
--
-- ხელით შემოწმება (გამყიდველის ანგარიშით): პანელში პაკეტის მოთხოვნა მუშაობს;
-- პაკეტის შეცვლა ახალ მოთხოვნაზე ძველ pending-ს „cancelled“-ზე გადაიყვანს;
-- ადმინში დადასტურება/უარყოფა მუშაობს.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK
--
-- ⚠️ ამის შემდეგ გამყიდველს ისევ შეუძლია status/resolved_at/tier-ის თვითნებური
--    მნიშვნელობით INSERT. backend-ის კოდს rollback არ სჭირდება.
--
--   begin;
--   alter table public.upgrade_requests drop constraint if exists upgrade_requests_status_chk;
--   alter table public.upgrade_requests drop constraint if exists upgrade_requests_tier_chk;
--   drop policy if exists "ur_owner_insert" on public.upgrade_requests;
--   create policy "ur_owner_insert" on public.upgrade_requests
--     for insert with check (
--       exists (select 1 from public.shops s
--               where s.id = upgrade_requests.shop_id and s.owner_id = auth.uid())
--     );
--   commit;
-- ----------------------------------------------------------------------------
