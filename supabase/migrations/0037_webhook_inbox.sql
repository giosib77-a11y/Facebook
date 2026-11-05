-- ============================================================================
-- 0037: webhook_inbox — მდგრადი webhook-ის რიგი + dedup ბაზაში (A-040 / N-05, Stage 21)
--
-- დანიშნულება
-- აქამდე Meta-ს webhook-ის მოვლენა მეხსიერებაში მუშავდებოდა (BackgroundTasks) და dedup-იც მეხსიერებაში იყო
-- (`_SEEN_MIDS`): restart / deploy-ის overlap / რამდენიმე instance-ი მოვლენას კარგავდა ან აორმაგებდა.
-- ახლა `receive_webhook` თითო `messaging` მოვლენას (ერთი `message.mid`) 200-მდე წერს `webhook_inbox`-ში,
-- ხოლო იმავე სერვისის worker-ი (FastAPI lifespan) ამუშავებს:
--   * `unique (page_id, mid)` — ერთდროულად რიგიც და dedup: Meta-ს განმეორება `ON CONFLICT DO NOTHING`-ით ქრება;
--   * `claim_webhook_events()` — `FOR UPDATE SKIP LOCKED`: რამდენიმე worker/instance ერთსა და იმავე მწკრივს ვერ აიღებს;
--     `processing` მწკრივი, რომელიც `p_stale_seconds`-ზე დიდხანს ჩარჩა (crash), ისევ აიღება;
--   * `attempts` ≥ `p_max_attempts` → მწკრივი აღარ იღება (`failed` ან ბოლო მცდელობაზე ჩარჩენილი).
-- PostgREST row-lock-ს ვერ აკეთებს — ამიტომ აღება RPC-ითაა.
--
-- უსაფრთხოება
-- backend-only: RLS ჩართულია, პოლისი არ არის; anon/authenticated-ს არავითარი grant — მხოლოდ service_role.
-- `event` (jsonb) შეიცავს კლიენტის შეტყობინებას და PSID-ს: ინახება მხოლოდ დამუშავებამდე; `done` → `event = null`
-- (backend წერს), ყველა მწკრივი 24 სთ-ში იშლება (`purge_webhook_inbox`, pg_cron ყოველ საათს :23-ზე).
-- `last_error` — მხოლოდ exception-ის კლასის სახელი (≤200 სიმბოლო).
-- ორივე ფუნქცია SECURITY INVOKER-ია (არა definer), `search_path = ''`; EXECUTE მოხსნილია public/anon/authenticated-დან —
-- PostgREST-ით (`/rpc/...`) ვერავინ გამოიძახებს გარდა service_role-ის (claim).
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე webhook ძველ in-process გზაზეა + ერთჯერადი WARNING
--    ლოგში; ცხრილის გამოჩენისთანავე backend გადაერთვება restart-ის გარეშე.
--
-- იდემპოტენტურია: if not exists / create or replace / `cron.schedule` იმავე სახელით არსებულ job-ს ანახლებს (0030-ის
-- მსგავსად); pg_cron იქმნება მხოლოდ თუ ჯერ არ არის (DO ბლოკი — Supabase-ის event trigger ჩართულზე ვარდება).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create table if not exists public.webhook_inbox (
  id              bigint generated always as identity primary key,
  page_id         text not null check (page_id ~ '^[0-9]{1,32}$'),
  mid             text not null check (char_length(mid) between 1 and 200),
  object          text not null check (object in ('page', 'instagram')),
  event           jsonb,
  status          text not null default 'pending' check (status in ('pending', 'processing', 'done', 'failed')),
  attempts        integer not null default 0 check (attempts >= 0),
  next_attempt_at timestamptz not null default now(),
  claimed_at      timestamptz,
  last_error      text check (char_length(last_error) <= 200),
  created_at      timestamptz not null default now(),
  processed_at    timestamptz,
  constraint webhook_inbox_page_mid_key unique (page_id, mid)
);

create index if not exists webhook_inbox_status_next_idx on public.webhook_inbox (status, next_attempt_at);
create index if not exists webhook_inbox_created_idx on public.webhook_inbox (created_at);

alter table public.webhook_inbox enable row level security;

revoke all on table public.webhook_inbox from public, anon, authenticated;
grant select, insert, update, delete on table public.webhook_inbox to service_role;
grant usage, select on sequence public.webhook_inbox_id_seq to service_role;

create or replace function public.claim_webhook_events(p_limit integer, p_stale_seconds integer, p_max_attempts integer)
returns setof public.webhook_inbox
language sql
volatile
set search_path = ''
as $$
  update public.webhook_inbox w
     set status = 'processing', claimed_at = now(), attempts = w.attempts + 1
   where w.id in (
     select i.id
       from public.webhook_inbox i
      where i.attempts < p_max_attempts
        and ((i.status = 'pending' and i.next_attempt_at <= now())
          or (i.status = 'processing' and i.claimed_at < now() - make_interval(secs => p_stale_seconds)))
      order by i.id
      limit greatest(1, least(p_limit, 50))
      for update skip locked
   )
  returning w.*
$$;

revoke execute on function public.claim_webhook_events(integer, integer, integer) from public, anon, authenticated;
grant execute on function public.claim_webhook_events(integer, integer, integer) to service_role;

create or replace function public.purge_webhook_inbox(p_hours integer)
returns integer
language plpgsql
set search_path = ''
as $$
declare
  v_deleted integer;
begin
  if p_hours < 0 then
    raise exception 'p_hours must be >= 0';
  end if;
  delete from public.webhook_inbox where created_at < now() - make_interval(hours => p_hours);
  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

revoke execute on function public.purge_webhook_inbox(integer) from public, anon, authenticated;

-- pg_cron ჩვეულებრივ უკვე ჩართულია (0030). `create extension` მხოლოდ მაშინ, თუ არ არის: Supabase-ის
-- pg_cron event trigger `create extension`-ზე `if not exists`-ის დროსაც ეშვება და ჩართულ pg_cron-ზე
-- 2BP01-ით ვარდება ("dependent privileges exist") — მთელი migration rollback-დება.
do $$
begin
  if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_cron') then
    create extension pg_cron with schema pg_catalog;
    grant usage on schema cron to postgres;
    grant all privileges on all tables in schema cron to postgres;
  end if;
end
$$;

select cron.schedule(
  'purge-webhook-inbox',
  '23 * * * *',  -- ყოველ საათს :23-ზე
  $$select public.purge_webhook_inbox(24)$$
);

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     (select relrowsecurity from pg_class where oid = 'public.webhook_inbox'::regclass)       as rls_on,     -- t
--     (select count(*) from pg_policies
--       where schemaname = 'public' and tablename = 'webhook_inbox')                            as policies,   -- 0
--     has_table_privilege('anon',          'public.webhook_inbox', 'select')                    as anon_sel,   -- f
--     has_table_privilege('anon',          'public.webhook_inbox', 'insert')                    as anon_ins,   -- f
--     has_table_privilege('authenticated', 'public.webhook_inbox', 'select')                    as auth_sel,   -- f
--     has_table_privilege('authenticated', 'public.webhook_inbox', 'insert')                    as auth_ins,   -- f
--     has_table_privilege('service_role',  'public.webhook_inbox', 'insert')                    as svc_ins,    -- t
--     has_table_privilege('service_role',  'public.webhook_inbox', 'update')                    as svc_upd;    -- t
--
--   select
--     has_function_privilege('authenticated', 'public.claim_webhook_events(integer,integer,integer)', 'execute') as claim_auth,  -- f
--     has_function_privilege('service_role',  'public.claim_webhook_events(integer,integer,integer)', 'execute') as claim_svc,   -- t
--     has_function_privilege('authenticated', 'public.purge_webhook_inbox(integer)', 'execute')                  as purge_auth;  -- f
--
--   select jobname, schedule, command, active from cron.job where jobname = 'purge-webhook-inbox';
--   -- სწორი შედეგი: 1 მწკრივი, '23 * * * *', ... purge_webhook_inbox(24), true
--
--   select * from public.claim_webhook_events(1, 180, 3);
--   -- სწორი შედეგი: 0 მწკრივი, შეცდომის გარეშე (ცარიელი ცხრილი)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; backend ძველ in-process გზაზე გადადის):
--   select cron.unschedule('purge-webhook-inbox');
--   drop function if exists public.purge_webhook_inbox(integer);
--   drop function if exists public.claim_webhook_events(integer, integer, integer);
--   drop table if exists public.webhook_inbox;
-- ============================================================================
