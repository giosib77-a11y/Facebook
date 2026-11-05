-- ============================================================================
-- 0040: products_search_trgm — ბოტის პროდუქტების ძებნა Postgres-ში: pg_trgm + RPC search_products (A-041 / N-04)
--
-- დანიშნულება
-- ბოტის `search_products` tool აქამდე ეძებდა მეხსიერებაში წაკითხულ პროდუქტებში (webhook ჭერი — 5 000).
-- დიდ კატალოგზე ეს ან ჭრის კატალოგს, ან ყოველ შეტყობინებაზე კითხულობს ათასობით მწკრივს. ახლა 300+ პროდუქტიან
-- მაღაზიაზე ძებნა ბაზაში სრულდება: `public.search_products(p_shop, p_terms, p_query, p_limit)` აბრუნებს
-- მხოლოდ საუკეთესო ≤20 მწკრივს, კატალოგის ზომის მიუხედავად (მოითხოვს 0028-ს: `image_description`, ლაივშია).
--
-- რას აკეთებს
--   * `pg_trgm` extension (`extensions` schema-ში) — თუ ჯერ არ არის; სხვა schema-ში აღმოჩენისას migration
--     ჩავარდება (raise exception) და მთლიანად rollback-დება — ნაწილობრივი მდგომარეობა არ რჩება;
--   * ორი GIN trigram index: `products.name`, `products.description` (ILIKE '%…%' ძებნის დასაჩქარებლად);
--   * RPC `search_products`: ქულა = რამდენი საძიებო სიტყვა (term) გვხვდება name / description / sku /
--     image_description-ში (იგივე წესი, რაც ბოტის `prompt.match_products`-ში: ქულა > 0, საუკეთესო პირველი).
--     ქულა თანაბარია → `similarity(name, query)` (trigram) — მხოლოდ რიგის tie-break, არა ფილტრი.
--     ქართულზე trigram Unicode-ზე მუშაობს, მაგრამ similarity-ს ხარისხი ქართულად გაუზომავია (ვარაუდი) —
--     ამიტომ ფილტრი და ქულა ILIKE-ზეა, similarity მხოლოდ თანაბარ ქულებს ალაგებს.
--   * term-ები: 2…50 სიმბოლო, უნიკალური, მაქს. 8 (ანბანით); `%`, `_`, `\` ILIKE-ში ეკრანირდება
--     (მომხმარებლის ტექსტი pattern-ად არასდროს ინტერპრეტირდება).
--
-- უსაფრთხოება
-- ფუნქცია SECURITY INVOKER (default), `set search_path = ''` (ყველა ობიექტი სქემით). tenant-ის ფილტრი
-- SQL-შია (`p.shop_id = p_shop`, მხოლოდ `is_active`); backend shop id-ს მხოლოდ ბოტის კონტექსტიდან იღებს.
-- EXECUTE `public` / `anon` / `authenticated`-ს ჩამორთმეულია და ენიჭება მხოლოდ `service_role`-ს:
-- გამყიდველი PostgREST-ით (`/rpc/search_products`) სხვის კატალოგს ვერ წაიკითხავს.
--
-- ⚠️ index-ის აგებისას `products`-ზე ჩაწერა მოკლედ იბლოკება (ცხრილი პატარაა — წამები) — გაუშვი მშვიდ დროს.
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). მის გარეშე ძებნა მეხსიერებაშია და ლოგში ერთჯერადი WARNING
--    ჩნდება; backend RPC-ს 10 წთ-ში ერთხელ ხელახლა ცდის — migration-ის შემდეგ restart **არ** სჭირდება.
--
-- იდემპოტენტურია: extension იქმნება მხოლოდ თუ არ არის (DO ბლოკი — Supabase-ის event trigger `create extension`-ზე
-- `if not exists`-ის დროსაც ეშვება და ჩართულზე 2BP01-ით ვარდება, იხ. 0034), create index if not exists,
-- create or replace function, revoke / grant განმეორებით უსაფრთხოა.
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

do $$
declare
  v_schema text;
begin
  if not exists (select 1 from pg_catalog.pg_extension where extname = 'pg_trgm') then
    create extension pg_trgm with schema extensions;
  end if;

  select n.nspname into v_schema
    from pg_catalog.pg_extension e
    join pg_catalog.pg_namespace n on n.oid = e.extnamespace
   where e.extname = 'pg_trgm';

  -- index-ები და ფუნქცია `extensions.`-ით მიმართავენ pg_trgm-ს; სხვა schema-ში (მაგ. public) ისინი არ იმუშავებს
  if v_schema is distinct from 'extensions' then
    raise exception 'pg_trgm is installed in schema %, expected extensions - stop and tell the agent', v_schema;
  end if;
end
$$;

create index if not exists products_name_trgm_idx on public.products using gin (name extensions.gin_trgm_ops);
create index if not exists products_description_trgm_idx on public.products using gin (description extensions.gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- search_products(p_shop, p_terms, p_query, p_limit): ≤20 საუკეთესო პროდუქტი (ქულა > 0), ქულა = დამთხვეული term-ების რაოდენობა
--   p_terms — საძიებო სიტყვები (backend-ი უკვე lower-case-ში აქცევს, stopword-ების გარეშე); p_query — similarity tie-break-ისთვის
-- ---------------------------------------------------------------------------
create or replace function public.search_products(p_shop uuid, p_terms text[], p_query text, p_limit integer)
returns table (id uuid, name text, price numeric, quantity integer, sku text, description text, score integer)
language sql
stable
set search_path = ''
as $$
  with terms as (
    -- 2…50 სიმბოლო, უნიკალური, მაქს. 8; ILIKE pattern-ში \ % _ ეკრანირებულია (ჯერ \, მერე % და _)
    select '%' || replace(replace(replace(t.term, '\', '\\'), '%', '\%'), '_', '\_') || '%' as pat
      from (select distinct u.term
              from unnest(coalesce(p_terms, '{}'::text[])) as u(term)
             where char_length(u.term) between 2 and 50
             order by u.term
             limit 8) t
  ),
  pats as (
    select coalesce(array_agg(terms.pat), '{}'::text[]) as arr from terms
  ),
  matched as (
    select p.id, p.name, p.price, p.quantity, p.sku, p.description,
           -- ქულა: რამდენი term გვხვდება რომელიმე ველში (prompt.match_products: ერთი term ერთხელ ითვლება)
           (select count(*)
              from unnest((select arr from pats)) as x(pt)
             where p.name ilike x.pt
                or p.description ilike x.pt
                or p.sku ilike x.pt
                or p.image_description ilike x.pt)::integer as score
      from public.products p
     where p.shop_id = p_shop
       and p.is_active
       and (p.name ilike any((select arr from pats))
            or p.description ilike any((select arr from pats))
            or p.sku ilike any((select arr from pats))
            or p.image_description ilike any((select arr from pats)))
  )
  select m.id, m.name, m.price, m.quantity, m.sku, m.description, m.score
    from matched m
   order by m.score desc, extensions.similarity(m.name, coalesce(p_query, '')) desc, m.id
   limit greatest(1, least(coalesce(p_limit, 10), 20))
$$;

revoke execute on function public.search_products(uuid, text[], text, integer) from public, anon, authenticated;
grant execute on function public.search_products(uuid, text[], text, integer) to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select e.extname, n.nspname from pg_extension e join pg_namespace n on n.oid = e.extnamespace where e.extname = 'pg_trgm';
--   -- სწორი შედეგი: pg_trgm | extensions
--   select indexname from pg_indexes where schemaname = 'public' and indexname in ('products_name_trgm_idx', 'products_description_trgm_idx');
--   -- სწორი შედეგი: 2 მწკრივი
--   select has_function_privilege('authenticated', 'public.search_products(uuid, text[], text, integer)', 'EXECUTE');
--   -- სწორი შედეგი: f
--   select has_function_privilege('service_role', 'public.search_products(uuid, text[], text, integer)', 'EXECUTE');
--   -- სწორი შედეგი: t
--   select * from public.search_products((select id from public.shops limit 1), array['test'], 'test', 5);
--   -- სწორი შედეგი: 0+ მწკრივი შეცდომის გარეშე (სვეტები: id, name, price, quantity, sku, description, score)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; ბოტი დაუბრუნდება მეხსიერებაში ძებნას; extension **არ** იშლება):
--   drop function if exists public.search_products(uuid, text[], text, integer);
--   drop index if exists public.products_name_trgm_idx;
--   drop index if exists public.products_description_trgm_idx;
-- ============================================================================
