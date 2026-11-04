-- ============================================================================
-- 0033: bot_conversations.bot_paused_until — ბოტის პაუზა handoff-ის / გამყიდველის პასუხის შემდეგ (A-035)
--
-- დანიშნულება
-- Handoff-ის (`needs_attention`) შემდეგაც ბოტი კლიენტს ეკამათებოდა და გამყიდველის ხელით დაწერილ პასუხს
-- ეჯიბრებოდა. ახალი nullable სვეტი `bot_paused_until` ამას აჩერებს: handoff-ზე და გამყიდველის ხელით
-- დაწერილ ყოველ პასუხზე (Messenger echo) backend სვეტში წერს `now() + 12 საათს`; სანამ ეს დრო მომავალშია,
-- კლიენტის შეტყობინება ისტორიაში ინახება, მაგრამ ბოტი არ პასუხობს (არც LLM, არც გაგზავნა). 12 საათის
-- შემდეგ პაუზა თავისით იწურება; გამყიდველის პანელში „მოგვარებულია" მას ადრევე ხსნის (S20-4).
-- `null` = შეჩერებული არ არის.
--
-- 0030-ის retention-თან ურთიერთობა
--   * პაუზა 12 სთ < 24 სთ (საუბრის შენახვის ვადა), გარდა ამისა echo `updated_at`-ს ანახლებს —
--     საუბარი პაუზის განმავლობაში არ წაიშლება;
--   * ღია handoff (`needs_attention = true`) 0030-ით ისევ ≤30 დღე ინახება; ეს ცვლილება არ ეხება.
--
-- უსაფრთხოება
-- სვეტს წერს მხოლოდ backend (service role). გამყიდველი კითხულობს 0008-ის არსებული SELECT პოლისით
-- (`bot_conversations` — საკუთარი მაღაზიის მწკრივები); ახალი grant / პოლისი არ არის და არ იცვლება.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე პაუზა გამორთულია: backend სვეტის არქონისას
--    echo-ს ტექსტს მაინც ინახავს ისტორიაში (`role: "operator"`), handoff ძველებურად მუშაობს და ლოგში
--    ერთჯერადი WARNING ჩნდება.
--
-- იდემპოტენტურია (`add column if not exists`; `comment on` განმეორებით უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.bot_conversations
  add column if not exists bot_paused_until timestamptz;

comment on column public.bot_conversations.bot_paused_until is
  'ბოტი ამ საუბარს არ პასუხობს, სანამ ეს დრო მომავალშია (handoff / გამყიდველის პასუხი + 12 სთ); null — შეჩერებული არ არის';

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select data_type, is_nullable from information_schema.columns
--   where table_schema = 'public' and table_name = 'bot_conversations' and column_name = 'bot_paused_until';
--   -- სწორი შედეგი: timestamp with time zone, YES
--
--   select count(*) from pg_policies where schemaname = 'public' and tablename = 'bot_conversations';
--   -- სწორი შედეგი: უცვლელი (1)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; backend პაუზის გარეშე გააგრძელებს):
--   alter table public.bot_conversations drop column if exists bot_paused_until;
-- ============================================================================
