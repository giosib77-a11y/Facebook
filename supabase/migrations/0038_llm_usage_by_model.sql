-- ============================================================================
-- 0038: llm_usage_by_model — ხარჯის ბიუჯეტი დოლარში: ტოკენები მოდელების მიხედვით (A-048 / N-03)
--
-- დანიშნულება
-- backend-ს LLM-ის ხარჯი USD-ში უნდა დაითვალოს (Stage 21): ტოკენი ტოკენისგან ძვირია, მოდელისა და
-- ტიპის (input / output / cache_read / cache_write) მიხედვით. `llm_usage_by_model(p_owner, p_shop, p_since)`
-- აბრუნებს `llm_usage`-ის ოთხივე ტოკენის სვეტის ჯამს `(provider, model)` ჯგუფებად `p_since`-დან მოყოლებული;
-- ფასებს backend ამრავლებს (`LLM_PRICES`). ფილტრი: `p_shop` — მხოლოდ ეს მაღაზია; `p_owner` — ამ მფლობელის
-- ყველა მაღაზია; ორივე null — მთელი პლატფორმა. (0035-ის `llm_tokens_used` უცვლელია და backend-ში აღარ გამოიყენება.)
--
-- უსაფრთხოება
-- ფუნქცია SECURITY INVOKER (default) და `set search_path = ''` (ყველა ობიექტი სქემით). ის კითხულობს
-- `llm_usage`-ს და `shops`-ს; service_role-ს ორივეზე select აქვს (0025 / 0001), ამიტომ DEFINER საჭირო არ არის.
-- EXECUTE `public` / `anon` / `authenticated`-ს ჩამორთმეულია და ენიჭება მხოლოდ `service_role`-ს:
-- გამყიდველი PostgREST-ით პლატფორმის ხარჯს ვერ წაიკითხავს.
--
-- ⚠️ გაუშვი backend deploy-მდე (აუცილებელი ბიუჯეტისთვის). მის გარეშე ხარჯის ბიუჯეტი (დღიური, თვიური,
--    გლობალური) გამორთულია (PGRST202 → ლოგში ერთჯერადი WARNING; ბოტი მუშაობს); kill-switch მუშაობს.
--    ⚠️ migration-ის შემდეგ Render-ზე restart სჭირდება: backend-მა PGRST202-ის შემდეგ RPC-ს ამ პროცესში
--    აღარ ცდის.
--
-- იდემპოტენტურია (create or replace / revoke / grant განმეორებით უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create or replace function public.llm_usage_by_model(p_owner uuid, p_shop uuid, p_since timestamptz)
returns table (
  provider text,
  model text,
  input_tokens bigint,
  output_tokens bigint,
  cache_read_tokens bigint,
  cache_write_tokens bigint
)
language sql
stable
set search_path = ''
as $$
  select u.provider,
         u.model,
         sum(u.input_tokens)::bigint,
         sum(u.output_tokens)::bigint,
         sum(u.cache_read_tokens)::bigint,
         sum(u.cache_write_tokens)::bigint
  from public.llm_usage u
  where u.created_at >= p_since
    and (p_shop is null or u.shop_id = p_shop)
    and (p_owner is null
         or u.shop_id in (select s.id from public.shops s where s.owner_id = p_owner))
  group by u.provider, u.model
$$;

revoke execute on function public.llm_usage_by_model(uuid, uuid, timestamptz)
  from public, anon, authenticated;
grant execute on function public.llm_usage_by_model(uuid, uuid, timestamptz)
  to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select has_function_privilege('authenticated', 'public.llm_usage_by_model(uuid,uuid,timestamptz)', 'EXECUTE');
--   -- სწორი შედეგი: f
--   select has_function_privilege('service_role', 'public.llm_usage_by_model(uuid,uuid,timestamptz)', 'EXECUTE');
--   -- სწორი შედეგი: t
--   select * from public.llm_usage_by_model(null, null, date_trunc('month', now()));
--   -- სწორი შედეგი: ერთი მწკრივი თითო (provider, model)-ზე, ტოკენების ჯამებით (ცარიელი, თუ ამ თვეში გამოძახება არ ყოფილა)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; ხარჯის ბიუჯეტი გამოირთვება):
--   drop function if exists public.llm_usage_by_model(uuid, uuid, timestamptz);
-- ============================================================================
