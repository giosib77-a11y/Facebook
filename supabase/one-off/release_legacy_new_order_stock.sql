-- ============================================================================
-- ONE-OFF (არა ნუმერირებული მიგრაცია): ძველი წესით შექმნილი `new` შეკვეთების
-- მარაგის დაბრუნება (T20)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- ძველი წესით (deploy-მდე) `create_order` მარაგს შეკვეთის შექმნისთანავე ამცირებდა
-- (decrement_stock). ახალი წესით (PROJECT.md: „მარაგი იკლებს მხოლოდ new → processing")
-- `new` შეკვეთას მარაგი ჩამოჭრილი არ აქვს. ამიტომ deploy-მდე შექმნილ, ჯერ კიდევ
-- `new` შეკვეთებზე:
--   * new → processing მარაგს მეორედ დააკლებდა (ან 409-ს მისცემდა);
--   * new → cancelled მარაგს არასოდეს დააბრუნებდა (ახალი კოდი `new`-ზე არაფერს აბრუნებს).
-- processing/done შეკვეთები კონსისტენტურია (მათზე მარაგი ორივე წესით ჩამოჭრილია) —
-- მათ ეს სკრიპტი არ ეხება.
--
-- გამოსავალი: ყველა „ძველი" `new` შეკვეთის მარაგს ერთხელ ვაბრუნებთ
-- (apply_stock_delta, sign = +1). ამის შემდეგ ისინი ახალ წესს ემთხვევა: „მარაგი
-- ჩამოჭრილი არ არის", და new → processing ჩვეულებრივად დააკლებს.
--
-- ᲠᲝᲜᲘ ᲒᲐᲕᲣᲨᲕᲐ
-- backend-ის ახალი ვერსიის deploy-ის შემდეგ, **მაშინვე** (რაც ნაკლები დრო გავა, მით
-- ნაკლებია ფანჯარა, როცა ძველი `new` შეკვეთა გაუქმდება/დადასტურდება ახალი კოდით
-- გასწორებამდე — იხ. „შეზღუდვა" ქვემოთ).
-- გაშვება: Supabase → SQL Editor (postgres როლი). სკრიპტი ხელით, ნაბიჯ-ნაბიჯ.
--
-- ᲠᲝᲒᲝᲠ ᲐᲕᲠᲩᲘᲝ CUTOFF
-- cutoff = მომენტი, როცა ახალმა backend-მა ტრაფიკის მიღება დაიწყო (Render →
-- Events → ახალი deploy-ის „live" დრო, UTC-ში, ISO ფორმატით, მაგ.
-- '2026-10-09T08:15:00Z'). `created_at < cutoff` = ძველი წესით შექმნილი შეკვეთები.
-- ახალი ინსტანციით შექმნილ `new` შეკვეთებს მარაგი არასოდეს ჩამოჭრილა — მათ ხელი
-- არ უნდა ახლდეს. ზედმეტად გვიანი cutoff ახალი ინსტანციის შეკვეთებს დაიჭერდა (მარაგი
-- გაიბერებოდა); ზედმეტად ადრეული — ძველებს გამოტოვებდა. ზუსტად „live" მომენტი აიღე.
-- Render-ის zero-downtime deploy-ზე ორი ინსტანცია ცოტა ხანს ერთად მუშაობს: ამ
-- ფანჯარის შეკვეთები ორაზროვანია — STEP 1a-ში შეხედე newest-ს და ეჭვის შემთხვევაში
-- ამ შეკვეთებს ხელით შეხედე.
--
-- ᲠᲐ ᲙᲐᲜᲔᲑᲘᲗ ᲓᲐᲛᲝᲙᲘᲓᲔᲑᲣᲚᲘᲐ
-- cutoff ორ ადგილას ჩაწერე (ძებნა: `EDIT_CUTOFF`): STEP 1 და STEP 2. ორივეგან ერთი
-- და იგივე მნიშვნელობა. სანამ placeholder '2099-01-01T00:00:00Z' რჩება, STEP 2
-- EXCEPTION-ით ჩერდება და არაფერს ცვლის; STEP 1 ცარიელ შედეგს აჩვენებს.
--
-- ᲨᲔᲖᲦᲣᲓᲕᲐ
-- deploy-სა და ამ სკრიპტის გაშვებას შორის ძველი `new` შეკვეთა რომ გაუქმდეს ან
-- processing-ზე გადავიდეს, ახალი კოდით: cancelled → მარაგი არ დაბრუნდება (STEP 2
-- მას ვეღარ იპოვის, სტატუსი `new` აღარაა); processing → მარაგი მეორედ დაიკლება.
-- ამიტომ გაუშვი deploy-ის შემდეგ დაუყოვნებლივ. შემდეგ ამ ფანჯარაში შეცვლილი
-- შეკვეთები ხელით გადაამოწმე: updated_at >= cutoff და created_at < cutoff.
--
-- ᲓᲣᲑᲚᲘ ᲒᲐᲨᲕᲔᲑᲘᲡ ᲓᲐᲪᲕᲐ
-- STEP 2 პირველ რიგში ჩასვამს მარკერს public._one_off_runs-ში (PK = name). მეორე
-- გაშვებაზე PK-ის დარღვევა მთელ ტრანზაქციას აბათილებს — მარაგი ორჯერ არ დაბრუნდება.
--
-- ROLLBACK
-- STEP 2 ერთი ტრანზაქციაა (DO ბლოკი): შეცდომისას ყველაფერი ბათილდება, მარკერიც.
-- დასრულებულის უკან დაბრუნება ავტომატური არ არის (მარაგი უკვე გაზრდილია, შესაძლოა
-- გამყიდველმა შემდეგ ხელითაც შეცვალა). თუ აუცილებელია: ამ სკრიპტის STEP 1 query-თი
-- (იგივე cutoff) აიღე გაერთიანებული (shop_id, product_id, quantity) და ხელით
-- გამოაკელი, შემდეგ `delete from public._one_off_runs where name = 'release_legacy_new_order_stock';`.
-- ღირს ჯერ STEP 1 შედეგის ჩაწერა/ეკრანის შენახვა, სანამ STEP 2-ს გაუშვებ.
--
-- შენიშვნა: პროდუქტი, რომელიც შეკვეთის შემდეგ წაიშალა, apply_stock_delta-ში უბრალოდ
-- გამოიტოვება (UPDATE 0 მწკრივს ეხება). greatest(0, …) აქ მხოლოდ ზრდაზე მუშაობს.
-- ============================================================================


-- ============================================================================
-- STEP 1 — PREVIEW (მხოლოდ წაკითხვა, არაფერს ცვლის)
-- გაუშვი ცალკე. cutoff შეცვალე EDIT_CUTOFF-ის ადგილას.
-- ============================================================================

-- 1a. რამდენი შეკვეთა დაექვემდებარება დაბრუნებას
with cfg as (
  select '2099-01-01T00:00:00Z'::timestamptz as cutoff   -- EDIT_CUTOFF
)
select count(*) as orders_to_process,
       min(o.created_at) as oldest,
       max(o.created_at) as newest   -- newest უნდა იყოს deploy-მდე!
  from public.orders o, cfg
 where o.status = 'new' and o.created_at < cfg.cutoff;

-- 1b. რა რაოდენობა დაბრუნდება მაღაზიის/პროდუქტის მიხედვით
with cfg as (
  select '2099-01-01T00:00:00Z'::timestamptz as cutoff   -- EDIT_CUTOFF
)
select o.shop_id,
       (it->>'product_id') as product_id,
       p.name              as product_name,
       p.quantity          as current_stock,
       sum(coalesce((it->>'quantity')::int, 0)) as will_be_released
  from public.orders o
  cross join cfg
  cross join lateral jsonb_array_elements(o.items) as it
  left join public.products p
         on p.id = (it->>'product_id')::uuid and p.shop_id = o.shop_id
 where o.status = 'new' and o.created_at < cfg.cutoff
   and coalesce((it->>'quantity')::int, 0) > 0
 group by o.shop_id, (it->>'product_id'), p.name, p.quantity
 order by o.shop_id, product_name;
-- product_name = NULL → პროდუქტი წაშლილია, ამ ხაზზე არაფერი დაბრუნდება (მოსალოდნელია).


-- ============================================================================
-- STEP 2 — APPLY (ერთი ტრანზაქცია; გაუშვი მხოლოდ STEP 1-ის გადამოწმების შემდეგ)
-- cutoff შეცვალე EDIT_CUTOFF-ის ადგილას (იგივე, რაც STEP 1-ში).
-- ============================================================================

create table if not exists public._one_off_runs (
  name    text primary key,
  ran_at  timestamptz not null default now(),
  details text
);
alter table public._one_off_runs enable row level security;   -- პოლისები არ არის განზრახ
revoke all on public._one_off_runs from public, anon, authenticated;

do $$
declare
  v_cutoff timestamptz := '2099-01-01T00:00:00Z';   -- EDIT_CUTOFF
  v_name   constant text := 'release_legacy_new_order_stock';
  r        record;
  v_count  int := 0;
begin
  -- guard: placeholder-ს ვერ გაუშვებ
  if v_cutoff >= '2099-01-01T00:00:00Z'::timestamptz then
    raise exception 'CUTOFF ჯერ არ არის შეცვლილი (placeholder 2099-01-01). ჩაწერე deploy-ის live დრო.';
  end if;
  -- guard: მომავალში ჩაწერილი cutoff ახალ შეკვეთებსაც დაიჭერდა
  if v_cutoff > now() then
    raise exception 'CUTOFF მომავალშია (%) — შეამოწმე დრო.', v_cutoff;
  end if;

  -- გაშვების მარკერი პირველად: მეორე გაშვებაზე PK-ის დარღვევა ყველაფერს აბათილებს
  insert into public._one_off_runs (name) values (v_name);

  -- FOR UPDATE: პარალელური status-ცვლილება ელოდება; სტატუსი ჩაკეტვის შემდეგ ისევ მოწმდება
  for r in
    select id, shop_id, items
      from public.orders
     where status = 'new' and created_at < v_cutoff
     order by created_at
       for update
  loop
    perform public.apply_stock_delta(r.shop_id, r.items, 1);
    v_count := v_count + 1;
  end loop;

  update public._one_off_runs
     set details = format('cutoff=%s; orders_processed=%s', v_cutoff, v_count)
   where name = v_name;

  raise notice 'დამუშავდა შეკვეთა: %', v_count;
end $$;


-- ============================================================================
-- STEP 3 — VERIFY
-- ============================================================================

-- 3a. გაშვების მარკერი + დამუშავებული შეკვეთების რაოდენობა (details-ში)
select name, ran_at, details from public._one_off_runs
 where name = 'release_legacy_new_order_stock';
-- ცარიელია → STEP 2 არ შესრულებულა (ან გაუქმდა შეცდომით).
-- details: orders_processed უნდა დაემთხვეს STEP 1a-ის orders_to_process-ს.

-- 3b. რამდენიმე მაღაზიაზე შეადარე STEP 1b-ის current_stock + will_be_released
--     ახლანდელ მარაგს:
-- select id, name, quantity from public.products where shop_id = '<shop_id>' order by name;

-- 3c. ხელახლა გაშვება უნდა ჩავარდეს:
--     STEP 2-ის DO ბლოკი → ERROR: duplicate key value violates unique constraint
--     "_one_off_runs_pkey" (ეს სწორია — მარაგი არ შეიცვლება).
