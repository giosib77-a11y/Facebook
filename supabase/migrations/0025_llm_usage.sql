-- ============================================================================
-- 0025: llm_usage — LLM-ის token-ხარჯის აღრიცხვა მაღაზიების მიხედვით (S14-4)
--
-- დანიშნულება
-- ბოტი ყოველ LLM პასუხზე (Claude / OpenAI) backend-იდან წერს ერთ მწკრივს: რომელი მაღაზია,
-- რომელი provider/მოდელი, რამდენი input / output / cache-read / cache-write token.
-- საჭიროა ხარჯის გაზომვისთვის (Stage 15) და ტარიფების გადასამოწმებლად.
--
-- უსაფრთხოება
-- ცხრილი backend-only: RLS ჩართულია, პოლისი არ არსებობს, anon/authenticated-ს არანაირი
-- უფლება არ აქვს. წერს/კითხულობს მხოლოდ service_role (backend, secret key).
-- გამყიდველი PostgREST-ით ვერ დაწერს ყალბ მწკრივებს და ვერ წაიკითხავს სხვის ხარჯს.
--
-- ⚠️ გაუშვი backend deploy-მდე: ახალი backend ამ ცხრილში წერს. (ჩაწერის შეცდომა
--    ბოტს არ აჩერებს — backend მხოლოდ WARNING-ს ლოგავს — მაგრამ აღრიცხვა დაიკარგება.)
--
-- id: uuid (gen_random_uuid()) — როგორც 0001–0005 ცხრილებში (shops, products, orders,
-- upgrade_requests). shop_id uuid references shops(id) (0001: shops.id uuid).
--
-- იდემპოტენტურია (if not exists / revoke / grant ხელახლა გაშვებაზე უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create table if not exists public.llm_usage (
  id                 uuid primary key default gen_random_uuid(),
  shop_id            uuid not null references public.shops (id) on delete cascade,
  provider           text not null check (provider in ('claude', 'openai')),
  model              text not null,
  input_tokens       integer not null default 0 check (input_tokens >= 0),
  output_tokens      integer not null default 0 check (output_tokens >= 0),
  cache_read_tokens  integer not null default 0 check (cache_read_tokens >= 0),
  cache_write_tokens integer not null default 0 check (cache_write_tokens >= 0),
  created_at         timestamptz not null default now()
);

create index if not exists llm_usage_shop_created_idx
  on public.llm_usage (shop_id, created_at);

-- RLS ჩართულია და პოლისი განზრახ არ არის: PostgREST-ით (anon/authenticated) წვდომა ჩაკეტილია.
-- service_role RLS-ს გვერდს უვლის, მაგრამ table privilege მაინც სჭირდება (ქვემოთ).
alter table public.llm_usage enable row level security;

revoke all on table public.llm_usage from public, anon, authenticated;
grant select, insert on table public.llm_usage to service_role;
-- uuid id-ს sequence არ აქვს, ამიტომ sequence grant საჭირო არ არის.

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     (select relrowsecurity from pg_class
--       where oid = 'public.llm_usage'::regclass)                              as rls_on,          -- true
--     (select count(*) from pg_policies
--       where schemaname = 'public' and tablename = 'llm_usage')               as policies,        -- 0
--     has_table_privilege('anon',          'public.llm_usage', 'select')       as anon_select,     -- false
--     has_table_privilege('anon',          'public.llm_usage', 'insert')       as anon_insert,     -- false
--     has_table_privilege('authenticated', 'public.llm_usage', 'select')       as auth_select,     -- false
--     has_table_privilege('authenticated', 'public.llm_usage', 'insert')       as auth_insert,     -- false
--     has_table_privilege('service_role',  'public.llm_usage', 'insert')       as service_insert;  -- true
--
-- სწორი შედეგი: t, 0, f, f, f, f, t.
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; წაშლის აღრიცხულ ხარჯს):
--   drop table if exists public.llm_usage;
-- ============================================================================
