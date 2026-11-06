-- ============================================================================
-- 0041: admin_audit_log — ადმინის ყველა ცვლილების კვალი (A-043 / N-06, Stage 23)
--
-- დანიშნულება
-- ადმინის ყოველი ცვლილება (მაღაზიის შეცვლა/წაშლა, გეგმის მოთხოვნის დადასტურება/უარყოფა, ვადის გახანგრძლივება,
-- გამყიდველის recovery) ჩაიწერება აქ: ვინ (`admin_id`) / რა (`action`, მაგ. `shop.update`) / რაზე (`target` —
-- shop/request/owner id) / როდის (`created_at`). backend წერს ცვლილების წარმატებით დასრულების შემდეგ (best-effort).
--
-- უსაფრთხოება
-- backend-only: RLS ჩართულია, პოლისი არ არის; anon/authenticated-ს არავითარი grant — მხოლოდ service_role.
-- service_role-ს აქვს მხოლოდ `select` + `insert` (append-only): backend-ის ბაგი ან მოპარული secret key
-- API-ით ჩანაწერს ვერ შეცვლის და ვერ წაშლის. `postgres` როლი (SQL Editor) — შეუძლია, მფლობელის გადაწყვეტილებით.
-- `details` (jsonb, ≤ 2048 ბაიტი, მხოლოდ ობიექტი) — PII ან secret **არასდროს** (email, სახელი, token, ბმული):
-- backend-ში allow-list-ია (`services/admin_audit.py`, S23-3); აქ მხოლოდ id-ები, რიცხვები და ფლაგები ხვდება.
-- `admin_id`-ზე FK **არ არის** (`auth.users`-ზე): ადმინის ანგარიშის წაშლის შემდეგაც კვალი უნდა დარჩეს.
--
-- Retention
-- არ არის: ჩანაწერი ათეულობით თვეში, PII არ ინახება. საჭიროებისას — ხელით
-- `delete from public.admin_audit_log where created_at < ...` (postgres როლით) ან მომავალში pg_cron.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე ადმინი მუშაობს, მაგრამ ჩანაწერი არ იწერება
--    + ერთჯერადი WARNING ლოგში; ცხრილის გამოჩენისთანავე ჩაწერა იწყება restart-ის გარეშე.
--
-- იდემპოტენტურია: create table / index if not exists; revoke/grant/enable RLS განმეორებით უვნებელია.
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create table if not exists public.admin_audit_log (
  id         bigint generated always as identity primary key,
  admin_id   uuid not null,
  action     text not null check (action ~ '^[a-z_]+\.[a-z_]+$' and char_length(action) <= 64),
  target     text check (char_length(target) <= 64),
  details    jsonb not null default '{}'::jsonb
               check (jsonb_typeof(details) = 'object' and pg_column_size(details) <= 2048),
  created_at timestamptz not null default now()
);

create index if not exists admin_audit_log_created_at_idx on public.admin_audit_log (created_at desc);

alter table public.admin_audit_log enable row level security;

revoke all on table public.admin_audit_log from public, anon, authenticated, service_role;
grant select, insert on table public.admin_audit_log to service_role;

revoke all on sequence public.admin_audit_log_id_seq from public, anon, authenticated;
grant usage, select on sequence public.admin_audit_log_id_seq to service_role;

commit;

-- ----------------------------------------------------------------------------
-- შემოწმება (გაუშვი ცალ-ცალკე, commit-ის შემდეგ):
--
--   select relrowsecurity from pg_class where oid = 'public.admin_audit_log'::regclass;
--     -- მოსალოდნელი: t
--   select count(*) from pg_policies where schemaname = 'public' and tablename = 'admin_audit_log';
--     -- მოსალოდნელი: 0
--   select has_table_privilege('anon', 'public.admin_audit_log', 'select'),
--          has_table_privilege('authenticated', 'public.admin_audit_log', 'select'),
--          has_table_privilege('authenticated', 'public.admin_audit_log', 'insert'),
--          has_table_privilege('service_role', 'public.admin_audit_log', 'select'),
--          has_table_privilege('service_role', 'public.admin_audit_log', 'insert'),
--          has_table_privilege('service_role', 'public.admin_audit_log', 'update'),
--          has_table_privilege('service_role', 'public.admin_audit_log', 'delete');
--     -- მოსალოდნელი: f, f, f, t, t, f, f
--
-- ROLLBACK (⚠️ შლის კვალს — მხოლოდ აუცილებლობისას; backend ცხრილის გარეშე ისევ მუშაობს):
--   drop table if exists public.admin_audit_log;
-- ----------------------------------------------------------------------------
