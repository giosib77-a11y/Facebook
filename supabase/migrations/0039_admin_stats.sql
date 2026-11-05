-- ============================================================================
-- 0039: admin_stats — ადმინის აგრეგაცია SQL-ში: overview / growth / shops (A-041 / N-04)
--
-- დანიშნულება
-- ადმინ პანელის `GET /admin/overview`, `/admin/growth`, `/admin/shops` ცხრილებს (shops, orders, products,
-- bot_customers) მთლიანად Python-ში კითხულობდა და იქ ითვლიდა. PostgREST-ის პასუხი 1000 მწკრივით
-- იზღუდება (Supabase „Max rows"), ამიტომ 1000-ზე მეტ შეკვეთაზე/პროდუქტზე რიცხვები ჩუმად ცდებოდა
-- (შეკვეთების რაოდენობა, შემოსავალი, მაღაზიების პროდუქტები). ეს migration რიცხვებს ბაზაში ითვლის:
--   * `admin_overview_stats()` — საერთო მაჩვენებლები + მფლობელების განაწილება პაკეტებად (`owner_tiers`);
--   * `admin_growth(p_months)` — ახალი მაღაზიები და შეკვეთები თვეობრივად (მხოლოდ მონაცემიანი თვეები);
--   * `admin_shop_counts()` — თითო მაღაზიაზე პროდუქტების / შეკვეთების / ამ თვის ბოტ-კლიენტების რაოდენობა.
-- MRR-ს backend ითვლის (`TIER_PRICES` — ერთი წყარო); ნულოვან თვეებს backend ავსებს (`_last_months`).
--
-- რატომ jsonb
-- თითოეული ფუნქცია ერთ jsonb მნიშვნელობას აბრუნებს. set-returning RPC-ის პასუხსაც იგივე 1000-მწკრივიანი
-- ჭერი ეხება (`admin_shop_counts` მაღაზიების რაოდენობით გაიზრდებოდა), ერთ მნიშვნელობას — არა.
--
-- უსაფრთხოება
-- ფუნქციები SECURITY INVOKER (default) და `set search_path = ''` (ყველა ობიექტი სქემით). service_role
-- RLS-ს გვერდს უვლის და ოთხივე ცხრილზე select აქვს, ამიტომ DEFINER საჭირო არ არის.
-- EXECUTE `public` / `anon` / `authenticated`-ს ჩამორთმეულია და ენიჭება მხოლოდ `service_role`-ს:
-- გამყიდველი PostgREST-ით პლატფორმის სტატისტიკას ვერ წაიკითხავს.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე ადმინი Python-ის აგრეგაციაზეა (გვერდებით,
--    სწორი, მაგრამ ნელი) და ლოგში ერთჯერადი WARNING ჩნდება. migration-ის შემდეგ restart **არ** სჭირდება:
--    backend RPC-ს ყოველ მოთხოვნაზე ხელახლა ცდის.
--
-- იდემპოტენტურია (create or replace / revoke / grant განმეორებით უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- admin_overview_stats(): საერთო მაჩვენებლები (იგივე წესები, რაც api/admin.py::overview-ში)
-- ---------------------------------------------------------------------------
create or replace function public.admin_overview_stats()
returns jsonb
language sql
stable
set search_path = ''
as $$
  select jsonb_build_object(
    'total_shops', (select count(*) from public.shops),
    'total_sellers', (select count(distinct s.owner_id) from public.shops s where s.owner_id is not null),
    'connected_shops', (select count(*) from public.shops s where coalesce(s.facebook_page_id, '') <> ''),
    'total_products', (select count(*) from public.products),
    'total_orders', (select count(*) from public.orders),
    'orders_30d', (select count(*) from public.orders o where o.created_at >= now() - interval '30 days'),
    -- შემოსავალი: გაუქმებული შეკვეთის გარდა ყველა (null status ითვლება, როგორც Python-ში)
    'revenue', (select coalesce(sum(o.total), 0) from public.orders o where o.status is distinct from 'cancelled'),
    -- მფლობელზე უმაღლესი პაკეტი (გამოწერა per-account-ია): core/tiers.best_tier-ის ასლი —
    -- რიგი free < basic < standard < business, უცნობი / null პაკეტი = free
    'owner_tiers', coalesce(
      (select jsonb_object_agg(ot.tier, ot.n)
         from (select t.tier, count(*) as n
                 from (select (array['free', 'basic', 'standard', 'business'])[
                                max(coalesce(array_position(array['free', 'basic', 'standard', 'business'],
                                                            s.subscription_tier), 1))
                              ] as tier
                         from public.shops s
                        where s.owner_id is not null
                        group by s.owner_id) t
                group by t.tier) ot),
      '{}'::jsonb)
  )
$$;

-- ---------------------------------------------------------------------------
-- admin_growth(p_months): {"YYYY-MM": {"shops": n, "orders": n}} ბოლო p_months თვისთვის (1…24, default 6)
-- ---------------------------------------------------------------------------
create or replace function public.admin_growth(p_months integer)
returns jsonb
language sql
stable
set search_path = ''
as $$
  with bounds as (
    -- თვის დასაწყისი UTC-ში: მიმდინარე თვე + წინა (m - 1) თვე
    select date_trunc('month', now() at time zone 'utc')
           - make_interval(months => greatest(1, least(coalesce(p_months, 6), 24)) - 1) as since
  ),
  shops_m as (
    select to_char(s.created_at at time zone 'utc', 'YYYY-MM') as ym, count(*) as n
      from public.shops s, bounds b
     where s.created_at at time zone 'utc' >= b.since
     group by 1
  ),
  orders_m as (
    select to_char(o.created_at at time zone 'utc', 'YYYY-MM') as ym, count(*) as n
      from public.orders o, bounds b
     where o.created_at at time zone 'utc' >= b.since
     group by 1
  ),
  months as (
    select ym from shops_m
    union
    select ym from orders_m
  )
  select coalesce(
    jsonb_object_agg(
      m.ym,
      jsonb_build_object('shops', coalesce(sm.n, 0), 'orders', coalesce(om.n, 0))
    ),
    '{}'::jsonb)
  from months m
  left join shops_m sm on sm.ym = m.ym
  left join orders_m om on om.ym = m.ym
$$;

-- ---------------------------------------------------------------------------
-- admin_shop_counts(): {"<shop_id>": {"products": n, "orders": n, "customers": n}} ყველა მაღაზიაზე
-- customers = bot_customers-ის მწკრივები მიმდინარე თვეზე (ym ფორმულა = track_bot_customer-ის, 0004)
-- ---------------------------------------------------------------------------
create or replace function public.admin_shop_counts()
returns jsonb
language sql
stable
set search_path = ''
as $$
  select coalesce(
    jsonb_object_agg(
      s.id::text,
      jsonb_build_object(
        'products', coalesce(p.n, 0),
        'orders', coalesce(o.n, 0),
        'customers', coalesce(c.n, 0)
      )
    ),
    '{}'::jsonb)
  from public.shops s
  left join (select shop_id, count(*) as n from public.products group by shop_id) p on p.shop_id = s.id
  left join (select shop_id, count(*) as n from public.orders group by shop_id) o on o.shop_id = s.id
  left join (select shop_id, count(*) as n from public.bot_customers
              where ym = to_char(now(), 'YYYY-MM') group by shop_id) c on c.shop_id = s.id
$$;

revoke execute on function public.admin_overview_stats() from public, anon, authenticated;
grant execute on function public.admin_overview_stats() to service_role;

revoke execute on function public.admin_growth(integer) from public, anon, authenticated;
grant execute on function public.admin_growth(integer) to service_role;

revoke execute on function public.admin_shop_counts() from public, anon, authenticated;
grant execute on function public.admin_shop_counts() to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select has_function_privilege('authenticated', 'public.admin_overview_stats()', 'EXECUTE');
--   select has_function_privilege('authenticated', 'public.admin_growth(integer)', 'EXECUTE');
--   select has_function_privilege('authenticated', 'public.admin_shop_counts()', 'EXECUTE');
--   -- სამივეს სწორი შედეგი: f
--   select has_function_privilege('service_role', 'public.admin_overview_stats()', 'EXECUTE');
--   select has_function_privilege('service_role', 'public.admin_growth(integer)', 'EXECUTE');
--   select has_function_privilege('service_role', 'public.admin_shop_counts()', 'EXECUTE');
--   -- სამივეს სწორი შედეგი: t
--   select public.admin_overview_stats();
--   -- სწორი შედეგი: total_orders = (select count(*) from public.orders), total_shops = (select count(*) from public.shops)
--   select public.admin_growth(6);
--   -- სწორი შედეგი: {"YYYY-MM": {"shops": n, "orders": n}, ...} — მხოლოდ მონაცემიანი თვეები, ბოლო 6 თვე
--   select count(*) from jsonb_object_keys(public.admin_shop_counts());
--   -- სწორი შედეგი: ტოლია (select count(*) from public.shops)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; ადმინი დაუბრუნდება Python-ის აგრეგაციას):
--   drop function if exists public.admin_overview_stats();
--   drop function if exists public.admin_growth(integer);
--   drop function if exists public.admin_shop_counts();
-- ============================================================================
