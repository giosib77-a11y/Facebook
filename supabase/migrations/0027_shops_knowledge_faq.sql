-- ============================================================================
-- 0027: shops.knowledge_faq — PDF-ის ტექსტის მოკლე FAQ (S17-1, Stage 17)
--
-- დანიშნულება
-- PDF-ის ატვირთვისას ბოტი ტექსტიდან ერთხელ აგენერირებს მოკლე FAQ-ს (≤3000 სიმბოლო, `Q:` / `A:` ხაზები)
-- და ინახავს აქ, იმავე მაღაზიის მწკრივში. ბოტის L2-ში (prompt) ცოდნის პირველი 20 000 სიმბოლოს ნაცვლად
-- ეს FAQ მიდის; სრული ტექსტი რჩება `shops.knowledge`-ში და `search_knowledge` მას ეძებს.
-- nullable: null = FAQ არ არის (ძველი ატვირთვა, FAQ-ის გენერაცია ჩავარდა, ცოდნა წაშლილია)
-- → ბოტი ცოდნის პირველ 20 000 სიმბოლოს იყენებს, როგორც აქამდე.
--
-- უსაფრთხოება
-- ჩაწერა მხოლოდ backend-იდან — `upload_knowledge` / `clear_knowledge` (service client, მფლობელობის
-- შემოწმების შემდეგ), როგორც `knowledge` 0022-ში. `authenticated`-ს `shops`-ზე ცხრილის დონის
-- INSERT/UPDATE არ აქვს (0015/0022), ხოლო სვეტის დონის UPDATE მხოლოდ `name, description, currency,
-- bot_language`-ზეა → ახალი სვეტი გამყიდველისთვის ჩაუწერადია. ამიტომ ამ ფაილში არც უფლების მიცემაა,
-- არც ჩამორთმევა, არც პოლისი (ახალ სვეტს ცხრილის დონის უფლება არ ეხება და column-level უფლება არავის აქვს).
-- SELECT — საკუთარი მაღაზიის RLS-ით (0001), ექსპორტშიც ჩანს.
-- FAQ იშლება მაღაზიის წაშლით (shops-ის მწკრივთან ერთად).
--
-- ⚠️ გაუშვი Stage 17-ის backend deploy-მდე (რეკომენდებული). backend სვეტის გარეშეც მუშაობს
--    (FAQ გამორთულია, ბოტი ძველ 20 000-იან ცოდნას იყენებს, ერთჯერადი WARNING ლოგში);
--    ძველ backend-ს ახალი სვეტი არ აწუხებს.
--
-- იდემპოტენტურია (add column if not exists / comment on ხელახლა გაშვებაზე უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.shops
  add column if not exists knowledge_faq text;

comment on column public.shops.knowledge_faq is
  'Stage 17: short FAQ generated from knowledge on upload (<=3000 chars); written only by the backend';

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select data_type, is_nullable
--   from information_schema.columns
--   where table_schema = 'public' and table_name = 'shops' and column_name = 'knowledge_faq';
--   -- სწორი შედეგი: text, YES
--
--   select
--     has_column_privilege('authenticated','public.shops','knowledge_faq','UPDATE') as faq_upd,
--     has_table_privilege('authenticated','public.shops','UPDATE')                  as tbl_upd,
--     has_column_privilege('authenticated','public.shops','knowledge_faq','SELECT') as faq_sel,
--     has_column_privilege('service_role','public.shops','knowledge_faq','UPDATE')  as svc_upd;
--   -- სწორი შედეგი: f, f, t, t
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; წაშლის შენახულ FAQ-ებს — ბოტი ძველ ქცევაზე დაბრუნდება):
--   alter table public.shops drop column if exists knowledge_faq;
-- ============================================================================
