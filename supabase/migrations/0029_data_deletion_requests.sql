-- ============================================================================
-- 0029: data_deletion_requests — Meta Data Deletion მოთხოვნების სტატუსი (A-017)
--
-- დანიშნულება
-- Meta-ს Data Deletion callback (`POST /facebook/data-deletion`) ყოველ მოთხოვნას აქ წერს:
-- ჯერ `pending`, წაშლის შემდეგ `completed` ან `failed`. status-გვერდი
-- (`GET /facebook/data-deletion/status`, `delete-data.html`) რეალურ სტატუსს აქედან კითხულობს —
-- ადრე ის ყოველთვის „completed"-ს აბრუნებდა, წაშლის შეცდომები კი იყლაპებოდა.
--
-- სვეტები
--   code        — დადასტურების კოდი (ხელმოწერილი, user_id-ს hash-ს შეიცავს და არა თავად id-ს)
--   fb_user_id  — Facebook user id, მხოლოდ სანამ წაშლა არ დასრულებულა (`failed`-ზე ხელახლა
--                 გასაშვებად); `completed`-ზე backend მას null-ით ცვლის
--   error       — შეცდომის კლასის სახელი (`failed`-ზე), PII-ის გარეშე
--
-- უსაფრთხოება
-- ცხრილი backend-only: RLS ჩართულია, პოლისი არ არსებობს, anon/authenticated-ს არანაირი
-- უფლება არ აქვს. წერს/კითხულობს მხოლოდ service_role (backend, secret key).
--
-- ⚠️ გაუშვი backend deploy-მდე: ახალი backend ცხრილის გარეშე callback-ზე 503-ს აბრუნებს
--    (მოთხოვნა ვერ ჩაიწერა → წაშლა არ იწყება, დადასტურება არ გაიცემა).
--
-- იდემპოტენტურია (if not exists / drop trigger if exists / revoke / grant ხელახლა გაშვებაზე უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create table if not exists public.data_deletion_requests (
  code        text primary key check (char_length(code) <= 200),
  fb_user_id  text check (char_length(fb_user_id) <= 100),
  status      text not null default 'pending' check (status in ('pending', 'completed', 'failed')),
  error       text check (char_length(error) <= 200),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

drop trigger if exists data_deletion_requests_set_updated_at on public.data_deletion_requests;
create trigger data_deletion_requests_set_updated_at
    before update on public.data_deletion_requests
    for each row execute function public.set_updated_at();

-- RLS ჩართულია და პოლისი განზრახ არ არის: PostgREST-ით (anon/authenticated) წვდომა ჩაკეტილია.
alter table public.data_deletion_requests enable row level security;

revoke all on table public.data_deletion_requests from public, anon, authenticated;
grant select, insert, update on table public.data_deletion_requests to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     (select relrowsecurity from pg_class
--       where oid = 'public.data_deletion_requests'::regclass)                          as rls_on,      -- true
--     (select count(*) from pg_policies
--       where schemaname = 'public' and tablename = 'data_deletion_requests')           as policies,    -- 0
--     has_table_privilege('anon',          'public.data_deletion_requests', 'select')  as anon_sel,    -- false
--     has_table_privilege('authenticated', 'public.data_deletion_requests', 'select')  as auth_sel,    -- false
--     has_table_privilege('authenticated', 'public.data_deletion_requests', 'insert')  as auth_ins,    -- false
--     has_table_privilege('service_role',  'public.data_deletion_requests', 'update')  as svc_upd;     -- true
--
-- სწორი შედეგი: t, 0, f, f, f, t.
--
-- ჩავარდნილი / დაუსრულებელი მოთხოვნები (ხელით გადასამოწმებლად):
--   select code, status, error, created_at from public.data_deletion_requests
--   where status <> 'completed' order by created_at desc;
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; status-გვერდი ყველა კოდზე „unknown"-ს აჩვენებს):
--   drop table if exists public.data_deletion_requests;
-- ============================================================================
