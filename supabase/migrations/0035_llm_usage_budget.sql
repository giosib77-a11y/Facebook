-- ============================================================================
-- 0035: llm_usage — ტოკენების ჯამი ბიუჯეტისთვის: ინდექსი + llm_tokens_used (A-037 / N-03)
--
-- დანიშნულება
-- backend-ს სჭირდება LLM-ის ხარჯის შემოწმება ბოტის პასუხამდე: (1) მფლობელის თვიური ტოკენების
-- ბიუჯეტი (პაკეტის მიხედვით) და (2) მთელი პლატფორმის დღიური ჭერი. `llm_tokens_used(p_owner, p_since)`
-- აბრუნებს `llm_usage`-ის ოთხივე ტოკენის სვეტის ჯამს (input + output + cache_read + cache_write)
-- `p_since`-დან მოყოლებული. `p_owner = null` — მთელი პლატფორმა, თორემ მხოლოდ ამ მფლობელის მაღაზიები.
-- ინდექსი `llm_usage (created_at)` პლატფორმის მასშტაბის (shop_id-ს გარეშე) დიაპაზონის შეკითხვას აჩქარებს
-- (არსებული `(shop_id, created_at)` ინდექსი მას ვერ ემსახურება).
--
-- უსაფრთხოება
-- ფუნქცია SECURITY INVOKER (default) და `set search_path = ''` (ყველა ობიექტი სქემით). ის კითხულობს
-- `llm_usage`-ს და `shops`-ს; service_role-ს ორივეზე select აქვს (0025 / 0001), ამიტომ DEFINER საჭირო არ არის.
-- EXECUTE `public` / `anon` / `authenticated`-ს ჩამორთმეულია და ენიჭება მხოლოდ `service_role`-ს:
-- გამყიდველი PostgREST-ით პლატფორმის ხარჯს ვერ წაიკითხავს.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე თვიური ბიუჯეტი და გლობალური დღიური ჭერი
--    გამორთულია (PGRST202 → ლოგში ერთჯერადი WARNING); kill-switch და კლიენტის დღიური ჭერი მუშაობს.
--
-- იდემპოტენტურია (if not exists / create or replace / revoke / grant განმეორებით უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create index if not exists llm_usage_created_idx
  on public.llm_usage (created_at);

create or replace function public.llm_tokens_used(p_owner uuid, p_since timestamptz)
returns bigint
language sql
stable
set search_path = ''
as $$
  select coalesce(sum(u.input_tokens + u.output_tokens + u.cache_read_tokens + u.cache_write_tokens), 0)::bigint
  from public.llm_usage u
  where u.created_at >= p_since
    and (p_owner is null
         or u.shop_id in (select s.id from public.shops s where s.owner_id = p_owner))
$$;

revoke execute on function public.llm_tokens_used(uuid, timestamptz)
  from public, anon, authenticated;
grant execute on function public.llm_tokens_used(uuid, timestamptz)
  to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select has_function_privilege('authenticated', 'public.llm_tokens_used(uuid,timestamptz)', 'EXECUTE');
--   -- სწორი შედეგი: f
--   select has_function_privilege('service_role', 'public.llm_tokens_used(uuid,timestamptz)', 'EXECUTE');
--   -- სწორი შედეგი: t
--   select public.llm_tokens_used(null, date_trunc('month', now()));
--   -- სწორი შედეგი: რიცხვი >= 0 (ამ თვეში პლატფორმის ჯამური ტოკენები)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; ბიუჯეტი და გლობალური დღიური ჭერი გამოირთვება):
--   drop function if exists public.llm_tokens_used(uuid, timestamptz);
--   drop index if exists public.llm_usage_created_idx;
-- ============================================================================
