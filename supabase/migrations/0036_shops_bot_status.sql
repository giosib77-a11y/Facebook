-- ============================================================================
-- 0036: shops.bot_status / bot_status_at — ბოტის ჯანმრთელობა (A-038 / N-07)
--
-- დანიშნულება
-- ბოტი ჩუმად კვდებოდა: ვადაგასული page token, გაშიფვრის შეცდომა, გაგზავნის ჩავარდნა — გამყიდველი
-- ამას ვერ ხედავდა. ახალი nullable სვეტები backend-ს ბოლო ცნობილ მდგომარეობას ახსოვნებს, ხოლო
-- პანელი (ან ადმინი) მას აჩვენებს:
--   bot_status    — 'ok' | 'token_error' (token-ის გაშიფვრა ვერ მოხერხდა) | 'token_expired' (Graph code 190)
--                   | 'send_failed' (გაგზავნა სხვა მიზეზით ჩავარდა) | 'budget_exhausted' (თვიური ბიუჯეტი ამოიწურა);
--                   null — ჯერ არ ჩაწერილა (უცნობი);
--   bot_status_at — ბოლო ცვლილების დრო.
-- backend წერს მხოლოდ ცვლილებაზე (ჯანსაღ გზაზე — არა), ამიტომ დამატებითი დატვირთვა უმნიშვნელოა.
-- CHECK-ის სახელი ავტომატურია (`shops_bot_status_check`); `add column if not exists` სვეტის არსებობისას
-- მთელ ქვეკომანდს, CHECK-ის ჩათვლით, გამოტოვებს — განმეორებით გაშვებისას დუბლირებული შეზღუდვა არ ჩნდება.
--
-- უსაფრთხოება
-- სვეტებს წერს მხოლოდ backend (service role). გამყიდველი (`authenticated`) მათ კითხულობს არსებული
-- SELECT-ით; UPDATE მას მხოლოდ 0015 / 0022-ში ჩამოთვლილ სვეტებზე აქვს (column-level grant) — ახალზე არა,
-- ამიტომ გამყიდველს სტატუსის გაყალბება არ შეუძლია. ახალი grant / პოლისი არ არის.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე ჯანმრთელობა არ იწერება (ლოგში ერთჯერადი
--    WARNING), ხოლო Telegram-ის BOT DOWN ალერტი მუშაობს.
--
-- იდემპოტენტურია (`add column if not exists`; `comment on` განმეორებით უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.shops
  add column if not exists bot_status text
    check (bot_status in ('ok', 'token_error', 'token_expired', 'send_failed', 'budget_exhausted'));

alter table public.shops
  add column if not exists bot_status_at timestamptz;

comment on column public.shops.bot_status is
  'ბოტის ბოლო ცნობილი მდგომარეობა: ok / token_error / token_expired / send_failed / budget_exhausted; null — უცნობი';
comment on column public.shops.bot_status_at is
  'bot_status-ის ბოლო ცვლილების დრო';

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select column_name, data_type, is_nullable from information_schema.columns
--   where table_schema = 'public' and table_name = 'shops' and column_name in ('bot_status', 'bot_status_at')
--   order by column_name;
--   -- სწორი შედეგი: bot_status — text, YES; bot_status_at — timestamp with time zone, YES
--
--   select has_column_privilege('authenticated', 'public.shops', 'bot_status', 'UPDATE');
--   -- სწორი შედეგი: f
--   select has_column_privilege('authenticated', 'public.shops', 'bot_status', 'SELECT');
--   -- სწორი შედეგი: t
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; backend ჯანმრთელობის ჩაწერის გარეშე გააგრძელებს):
--   alter table public.shops drop column if exists bot_status;
--   alter table public.shops drop column if exists bot_status_at;
-- ============================================================================
