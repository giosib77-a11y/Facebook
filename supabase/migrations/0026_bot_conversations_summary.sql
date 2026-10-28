-- ============================================================================
-- 0026: bot_conversations.summary — ძველი შეტყობინებების შეკუმშული ვერსია (S16-5, Stage 16)
--
-- დანიშნულება
-- ისტორია იზრდება 8-დან 16 შეტყობინებამდე; გადაჭარბებისას ბოტი უძველეს ნაწილს (ბოლო 8-ის გარდა)
-- ერთ მოკლე summary-ად (≤1200 სიმბოლო, ტელეფონის/მისამართის/email-ის გარეშე) აქცევს და ინახავს
-- აქ, იმავე მწკრივში (shop_id + psid). შემდეგ პასუხებში summary ისტორიის წინ ემატება prompt-ში.
-- nullable: null = summary ჯერ არ არსებობს (ახალი / მოკლე საუბრები).
--
-- უსაფრთხოება
-- ჩაწერა მხოლოდ backend-იდან (service_role, როგორც `messages`) — ახალი უფლება არ სჭირდება.
-- გამყიდველი საკუთარ მაღაზიის summary-ს კითხულობს 0008-ის `bot_conversations_owner_read`
-- პოლისით, როგორც დანარჩენ სვეტებს. ახალი პოლისი / უფლება / ფუნქცია ამ მიგრაციაში არ არის.
-- summary იშლება მაღაზიის წაშლით (on delete cascade, 0008) და Data Deletion callback-ით — როგორც `messages`.
--
-- ⚠️ გაუშვი Stage 16-ის backend deploy-მდე. backend სვეტის გარეშეც მუშაობს (summary გამორთულია,
--    ჭრა არ ხდება, ლოგში WARNING), მაგრამ სვეტის გარეშე ბოტი ძველ ქცევაზე რჩება.
--
-- იდემპოტენტურია (add column if not exists / comment on ხელახლა გაშვებაზე უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.bot_conversations
  add column if not exists summary text;

comment on column public.bot_conversations.summary is
  'Stage 16: short summary of the older messages (bot-generated, <=1200 chars, no personal data); written only by the backend';

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select data_type, is_nullable
--   from information_schema.columns
--   where table_schema = 'public' and table_name = 'bot_conversations' and column_name = 'summary';
--   -- სწორი შედეგი: text, YES
--
--   select count(*) from pg_policies
--   where schemaname = 'public' and tablename = 'bot_conversations';
--   -- სწორი შედეგი: 1 (უცვლელი — მხოლოდ bot_conversations_owner_read)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; წაშლის შენახულ summary-ებს):
--   alter table public.bot_conversations drop column if exists summary;
-- ============================================================================
