-- ============================================================================
-- 0043: shops.knowledge-ის სიგრძის ზღვარი 21 000 → 50 000 (A-042 / N-08, Stage 24)
--
-- დანიშნულება
-- 0016-ის `shops_knowledge_len_chk` (`char_length(knowledge) <= 21000`) Stage 17-მდე იყო დაწერილი. ახლა კოდი
-- PDF-ის ტექსტს ≤ 50 000 სიმბოლომდე ინახავს (`services/pdf_extract.MAX_CHARS = 50_000`), ამიტომ 21 000-ზე
-- გრძელი PDF-ის ატვირთვა ბაზაში `23514`-ით (check_violation) ვარდებოდა. ზღვარი ერთ ადგილზეა: DB-ის ჭერი =
-- კოდის ჭერი (ერთის შეცვლა მეორის გარეშე `tests/test_migration_0043.py`-ში წითელია).
--
-- უსაფრთხოება
-- constraint მხოლოდ ფართოვდება: არსებული მწკრივები ≤ 21 000 → ყველა გადის (`NOT VALID` არ არის საჭირო).
-- RLS / grant-ები / პოლისები არ იცვლება; `knowledge`-ის ჩაწერა მხოლოდ backend-ით (0015/0017: authenticated-ს
-- ამ სვეტზე UPDATE არ აქვს).
--
-- გაშვება — ნებისმიერ დროს, deploy-ზე დამოუკიდებლად (კოდი უკვე ≤ 50 000-ს ზღუდავს).
-- იდემპოტენტურია: `drop constraint if exists` + `add constraint`; განმეორებით გაშვება უვნებელია.
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.shops drop constraint if exists shops_knowledge_len_chk;
alter table public.shops add constraint shops_knowledge_len_chk check (char_length(knowledge) <= 50000);

commit;

-- ----------------------------------------------------------------------------
-- შემოწმება (გაუშვი commit-ის შემდეგ):
--
--   select pg_get_constraintdef(oid) from pg_constraint
--   where conrelid = 'public.shops'::regclass and conname = 'shops_knowledge_len_chk';
--     -- მოსალოდნელი: CHECK ((char_length(knowledge) <= 50000))
--
-- ROLLBACK (⚠️ ჯერ შეამოწმე: თუ max > 21 000, rollback ვერ გავა — ჯერ ის ცოდნა გაასუფთავე):
--   select max(char_length(knowledge)) from public.shops;
--
--   alter table public.shops drop constraint if exists shops_knowledge_len_chk;
--   alter table public.shops add constraint shops_knowledge_len_chk check (char_length(knowledge) <= 21000);
-- ----------------------------------------------------------------------------
