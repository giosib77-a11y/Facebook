-- ============================================================================
-- 0034: subscriptions — გამოწერის ვადა + ვადაგასულის დღიური დაქვეითება (pg_cron, A-036 / N-02)
--
-- დანიშნულება
-- ფასიანი პაკეტი (basic / standard / business) აქამდე უვადო იყო: ადმინი დაადასტურებდა გადახდას და
-- `shops.subscription_tier` სამუდამოდ რჩებოდა. ახლა მფლობელზე (per-account) ცალკე ცხრილი ინახავს
-- ვადას: `subscriptions (owner_id, tier, paid_until)`. ყოველდღე 00:05 UTC-ზე Supabase Cron (`pg_cron`)
-- იძახებს `public.expire_subscriptions()`-ს: ვადაგასული ფასიანი გამოწერა → `free`
--   * `subscriptions`-ში (`tier = 'free'`, `paid_until = null`);
--   * `shops.subscription_tier`-ში (სარკე) — მფლობელის ყველა მაღაზიაზე;
--   * ბოტების ჭერი: უფასო = 1 ჩართული ბოტი მფლობელზე, რჩება ყველაზე ძველი (`created_at`, `id`) ჩართული —
--     ეს `backend/app/services/bot_limits.py` `enforce_bot_limit`-ის SQL-ასლია (`TIER_LIMITS['free']['shops']`).
--     ბოტებს ადმინი/გამყიდველი თავად ხელახლა ჩართავს ახალი გადახდის შემდეგ.
--
-- რატომ რჩება `shops.subscription_tier` სარკედ
-- tier-ს კითხულობენ webhook, `create_shop` (+ RPC 0032), `enforce_bot_limit`, usage, ადმინ პანელი და
-- ტესტების ათეულები. სრული მოხსნა ფართო refactor იქნებოდა; სარკე წამკითხველებს უცვლელს ტოვებს,
-- ახალი ცხრილი მხოლოდ ვადას ამატებს. წყარო ვადისთვის — `subscriptions`, tier-ისთვის runtime-ში — სარკე.
--
-- backfill
-- ყველა მფლობელი, ვისაც რომელიმე მაღაზიაზე ფასიანი პაკეტი აქვს, იღებს მისი უმაღლესი პაკეტით
-- `paid_until = now() + 30 days` — პირველი cron (შემდეგი 00:05 UTC) არავის ეხება, ყველას +30 დღე აქვს.
--
-- უსაფრთხოება
-- RLS ჩართულია: გამყიდველი (authenticated) კითხულობს მხოლოდ საკუთარ მწკრივს (`owner_id = auth.uid()`),
-- INSERT/UPDATE/DELETE-ის grant-ი არ აქვს — ვადას წერს მხოლოდ backend (service_role).
-- `expire_subscriptions()` SECURITY INVOKER-ია (cron postgres როლით უშვებს, როგორც 0030-ში), `search_path = ''`;
-- EXECUTE მოხსნილია public/anon/authenticated-დან — PostgREST-ით (`/rpc/...`) ვერავინ გამოიძახებს.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). ხელახლა გაშვება უსაფრთხოა — backfill `on conflict do nothing`
--    (არსებული ვადა არ იცვლება); deploy-მდე/შემდეგ დამტკიცებული პაკეტების შესავსებად ხელახლა გაუშვი.
-- ⚠️ ცხრილის გარეშე backend მუშაობს: ვადა არ ჩაიწერება, ერთჯერადი WARNING ლოგში.
-- ⚠️ ვადის გასვლიდან cron-მდე ≤24 სთ პაკეტი მოქმედებს (grace).
--
-- იდემპოტენტურია: if not exists / drop policy if exists / on conflict do nothing / create or replace /
-- `cron.schedule` იმავე სახელით არსებულ job-ს ანახლებს (0030-ის მსგავსად) — დუბლი არ ჩნდება.
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create table if not exists public.subscriptions (
  owner_id   uuid primary key references auth.users (id) on delete cascade,
  tier       text not null default 'free' check (tier in ('free', 'basic', 'standard', 'business')),
  paid_until timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.subscriptions enable row level security;

drop policy if exists subscriptions_owner_read on public.subscriptions;
create policy subscriptions_owner_read on public.subscriptions
  for select to authenticated
  using (owner_id = (select auth.uid()));

revoke all on table public.subscriptions from public, anon, authenticated;
grant select on table public.subscriptions to authenticated;
grant select, insert, update on table public.subscriptions to service_role;

-- backfill: მფლობელის უმაღლესი ფასიანი პაკეტი, ვადა = ახლა + 30 დღე; არსებული მწკრივი არ იცვლება
insert into public.subscriptions (owner_id, tier, paid_until)
select owner_id,
       (array_agg(subscription_tier
                  order by array_position(array['free', 'basic', 'standard', 'business'], subscription_tier) desc))[1],
       now() + interval '30 days'
from public.shops
where owner_id is not null
  and subscription_tier in ('basic', 'standard', 'business')
group by owner_id
on conflict (owner_id) do nothing;

create or replace function public.expire_subscriptions()
returns integer
language plpgsql
set search_path = ''
as $$
declare
  v_owners uuid[];
begin
  -- 1) ვადაგასული ფასიანი გამოწერები → free
  with expired as (
    update public.subscriptions
       set tier = 'free', paid_until = null, updated_at = now()
     where tier <> 'free' and paid_until is not null and paid_until < now()
    returning owner_id
  )
  select array_agg(owner_id) into v_owners from expired;

  if v_owners is null then
    return 0;
  end if;

  -- 2) სარკე: მფლობელის ყველა მაღაზია free-ზე
  update public.shops set subscription_tier = 'free' where owner_id = any(v_owners);

  -- 3) ბოტების ჭერი: უფასო = 1 ჩართული ბოტი მფლობელზე, რჩება ყველაზე ძველი
  --    (`core/tiers.py` TIER_LIMITS['free']['shops'] = 1; `enforce_bot_limit`-ის ასლი)
  update public.shops s
     set bot_enabled = false
   where s.owner_id = any(v_owners)
     and s.bot_enabled
     and s.id <> (
       select s2.id from public.shops s2
        where s2.owner_id = s.owner_id and s2.bot_enabled
        order by s2.created_at, s2.id
        limit 1
     );

  return cardinality(v_owners);
end;
$$;

revoke execute on function public.expire_subscriptions() from public, anon, authenticated;

create extension if not exists pg_cron with schema pg_catalog;
grant usage on schema cron to postgres;
grant all privileges on all tables in schema cron to postgres;

select cron.schedule(
  'expire-subscriptions',
  '5 0 * * *',  -- ყოველდღე 00:05 UTC
  $$select public.expire_subscriptions()$$
);

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     (select relrowsecurity from pg_class where oid = 'public.subscriptions'::regclass)       as rls_on,     -- t
--     (select count(*) from pg_policies
--       where schemaname = 'public' and tablename = 'subscriptions')                            as policies,   -- 1
--     has_table_privilege('authenticated', 'public.subscriptions', 'select')                    as auth_sel,   -- t
--     has_table_privilege('authenticated', 'public.subscriptions', 'insert')                    as auth_ins,   -- f
--     has_table_privilege('authenticated', 'public.subscriptions', 'update')                    as auth_upd,   -- f
--     has_table_privilege('anon',          'public.subscriptions', 'select')                    as anon_sel,   -- f
--     has_table_privilege('service_role',  'public.subscriptions', 'update')                    as svc_upd;    -- t
--
--   select (select count(*) from public.subscriptions) as subscriptions,
--          (select count(distinct owner_id) from public.shops where subscription_tier <> 'free') as paid_owners;
--   -- სწორი შედეგი: ორი რიცხვი ტოლია
--
--   select jobname, schedule, command, active from cron.job where jobname = 'expire-subscriptions';
--   -- სწორი შედეგი: 1 მწკრივი, '5 0 * * *', ... expire_subscriptions(), true
--
--   select has_function_privilege('authenticated', 'public.expire_subscriptions()', 'execute') as auth_exec;
--   -- სწორი შედეგი: f
--
--   -- პირველი გაშვების შემდეგ (შემდეგი 00:05 UTC):
--   select status, return_message, start_time from cron.job_run_details
--   where jobid = (select jobid from cron.job where jobname = 'expire-subscriptions')
--   order by start_time desc limit 5;
--   -- სწორი შედეგი: status = 'succeeded'
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; shops-ის subscription_tier უცვლელი რჩება):
--   select cron.unschedule('expire-subscriptions');
--   drop function if exists public.expire_subscriptions();
--   drop table if exists public.subscriptions;
-- ============================================================================
