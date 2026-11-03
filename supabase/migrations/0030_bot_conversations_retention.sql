-- ============================================================================
-- 0030: bot_conversations — ვადაგასული საუბრების ავტომატური წაშლა (pg_cron, A-018)
--
-- დანიშნულება
-- ბოტი საუბრის ისტორიას მხოლოდ `BOT_MEMORY_HOURS` (default 24) საათის განმავლობაში იყენებს, მაგრამ
-- ჩანაწერი (კლიენტის შეტყობინებები + summary) აქამდე ბაზაში უვადოდ რჩებოდა. Render-ის უფასო გეგმაზე
-- cron არ არის, ამიტომ წაშლა ბაზაშივე ხდება: Supabase Cron (`pg_cron`) საათში ერთხელ იძახებს
-- `public.purge_expired_bot_conversations(24)`-ს.
--
-- რა იშლება
--   * საუბარი, რომლის ბოლო შეტყობინება (`updated_at`) `p_hours` საათზე ძველია;
--   * გამონაკლისი: `needs_attention = true` (კლიენტი ოპერატორს ელოდება) — რჩება, სანამ გამყიდველი
--     „მოგვარებულად" არ მონიშნავს, მაგრამ არაუმეტეს 30 დღისა (ჩაუხედავი handoff უვადოდ არ ინახება).
--     მონიშვნის შემდეგ მომდევნო გაშვება შლის.
-- `bot_customers` (თვიური ლიმიტის მრიცხველი, მხოლოდ psid) და `orders` არ იცვლება.
--
-- ⚠️ საათები (24) cron-ის ბრძანებაშია და backend-ის `BOT_MEMORY_HOURS`-ს უნდა ემთხვეოდეს. თუ Render-ზე
--    `BOT_MEMORY_HOURS` სხვაა, ხელახლა გაუშვი `cron.schedule(...)` ქვემოთ სწორი რიცხვით (backend
--    startup-ზე WARNING-ს წერს, თუ მნიშვნელობა 24 არ არის).
--
-- უსაფრთხოება
-- ფუნქცია SECURITY INVOKER-ია (cron postgres როლით უშვებს — ცხრილის მფლობელი), `search_path = ''`.
-- EXECUTE მოხსნილია public/anon/authenticated-დან — PostgREST-ით (`/rpc/...`) ვერავინ გამოიძახებს.
--
-- გაშვების რიგი: ნებისმიერ დროს (backend-ის ცვლილება არ სჭირდება; კოდი ამ ფუნქციას არ იძახებს).
-- იდემპოტენტურია: `if not exists` / `create or replace` / `cron.schedule` იმავე სახელით არსებულ job-ს ანახლებს.
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create extension if not exists pg_cron with schema pg_catalog;
grant usage on schema cron to postgres;
grant all privileges on all tables in schema cron to postgres;

create or replace function public.purge_expired_bot_conversations(p_hours integer)
returns integer
language plpgsql
set search_path = ''
as $$
declare
  n integer;
begin
  if p_hours is null or p_hours < 0 then
    raise exception 'p_hours must be >= 0';
  end if;
  delete from public.bot_conversations
   where updated_at < now() - make_interval(hours => p_hours)
     and (not needs_attention or updated_at < now() - interval '30 days');
  get diagnostics n = row_count;
  return n;
end;
$$;

revoke execute on function public.purge_expired_bot_conversations(integer) from public, anon, authenticated;

select cron.schedule(
  'purge-expired-bot-conversations',
  '17 * * * *',  -- საათში ერთხელ, :17 წუთზე
  $$select public.purge_expired_bot_conversations(24)$$
);

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select jobname, schedule, command, active from cron.job
--   where jobname = 'purge-expired-bot-conversations';
--   -- სწორი შედეგი: 1 მწკრივი, '17 * * * *', ... purge_expired_bot_conversations(24), true
--
--   select has_function_privilege('authenticated', 'public.purge_expired_bot_conversations(integer)', 'execute') as auth_exec,
--          has_function_privilege('anon',          'public.purge_expired_bot_conversations(integer)', 'execute') as anon_exec;
--   -- სწორი შედეგი: f, f
--
--   -- პირველი გაშვების შემდეგ (~1 სთ):
--   select status, return_message, start_time from cron.job_run_details
--   where jobid = (select jobid from cron.job where jobname = 'purge-expired-bot-conversations')
--   order by start_time desc limit 5;
--   -- სწორი შედეგი: status = 'succeeded'
--
--   select count(*) from public.bot_conversations
--   where updated_at < now() - interval '25 hours' and not needs_attention;
--   -- სწორი შედეგი (პირველი გაშვების შემდეგ): 0
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; უკვე წაშლილი საუბრები არ ბრუნდება):
--   select cron.unschedule('purge-expired-bot-conversations');
--   drop function if exists public.purge_expired_bot_conversations(integer);
-- ============================================================================
