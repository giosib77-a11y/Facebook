-- ============================================================================
-- 0042: llm_tokens_used (0035) წაშლა — ზედმეტი RPC (A-042 / N-08, Stage 24)
--
-- დანიშნულება
-- `llm_tokens_used(p_owner, p_since)` (0035) Stage 21-დან აღარ გამოიყენება: LLM-ის ბიუჯეტი USD-შია და
-- `llm_usage_by_model`-ით (0038) ითვლება. A-042: ერთი ქცევა, ზედმეტი RPC-ის გარეშე — Stage 24-ში
-- „migration არ გაშვებულა" fallback-ებიც წაიშალა, ამიტომ მკვდარ ფუნქციას არავითარი როლი აღარ აქვს.
-- ინდექსი `llm_usage_created_idx` (0035) **რჩება**: `llm_usage_by_model`-ის `created_at`-ის ფილტრი იყენებს.
--
-- უსაფრთხოება
-- ფუნქციას EXECUTE მხოლოდ `service_role`-ს ჰქონდა (public / anon / authenticated-ს ჩამორთმეული იყო);
-- წაშლა წვდომას არ ცვლის — არცერთ როლს არაფერი ემატება. ცხრილებს, პოლისებს, grant-ებს არ ეხება.
--
-- ⚠️ გაუშვი Stage 24-ის deploy-ის **შემდეგ** (deploy-მდეც უსაფრთხოა: ლაივის კოდი Stage 21-დან მას არ
--    იძახებს — `grep -rn llm_tokens_used backend/` → მხოლოდ ტესტები).
--
-- იდემპოტენტურია: `drop function if exists` — განმეორებით გაშვება უვნებელია.
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

drop function if exists public.llm_tokens_used(uuid, timestamptz);

commit;

-- ----------------------------------------------------------------------------
-- შემოწმება (გაუშვი ცალ-ცალკე, commit-ის შემდეგ):
--
--   select to_regprocedure('public.llm_tokens_used(uuid,timestamptz)');
--     -- მოსალოდნელი: null
--   select to_regprocedure('public.llm_usage_by_model(uuid,uuid,timestamptz)') is not null;
--     -- მოსალოდნელი: t
--
-- ROLLBACK (0035-ის ფაილის ხელახლა გაშვება — idempotent: `create or replace` + revoke / grant;
-- backend მას არ იძახებს, ამიტომ rollback საჭირო თითქმის არასდროსაა).
-- ----------------------------------------------------------------------------
