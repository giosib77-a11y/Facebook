-- ============================================================================
-- smoke_change_order_status: public.change_order_status-ის (მიგრაცია 0021) და
-- მასში ჩაშენებული მარაგის წესების SMOKE ტესტი რეალურ Postgres-ზე (S11-4)
--
-- ᲛᲘᲖᲐᲜᲘ
-- offline pytest-ები RPC-ს mock-ით ცვლიან, ამიტომ მარაგის წესები (plpgsql-ში)
-- ბაზაზე არასდროს გამოცდილა. ეს ფაილი მათ ცოცხალ ბაზაზე ამოწმებს.
--
-- ᲠᲐᲢᲝᲙ ᲐᲠᲘᲡ ᲣᲡᲐᲤᲠᲗᲮᲝ (safe by construction)
--   * მთელი ტესტი ერთი `DO $$ ... $$` ბლოკია = ერთი ტრანზაქცია.
--   * ბლოკის ბოლო ოპერატორი ყოველთვის `raise exception` (წარმატებაზეც:
--     'SMOKE OK — rolled back'), ამიტომ ტრანზაქცია ბათილდება და ბაზაში არაფერი რჩება
--     (არც დროებითი shop/products/orders, არც მარაგის ცვლილება).
--   * არ არის ტრანზაქციის დამფიქსირებელი ბრძანება, DDL (ცხრილის/ფუნქციის შექმნა ან წაშლა), დროებითი ცხრილი, NOTIFY,
--     storage-ის გამოძახება. UUID-ებს gen_random_uuid() იძლევა (sequence არ გამოიყენება).
--   * არსებული ცოცხალი მონაცემიდან იკითხება მხოლოდ ერთი `auth.users.id`
--     (shops.owner_id-სთვის); მის ანგარიშს არაფერი ეცვლება — სატესტო shop
--     ჩასმული და ტრანზაქციასთან ერთად გაუქმდება. სატესტო სახელები: '__SMOKE__...'.
--
-- ᲠᲝᲒᲐᲠ ᲒᲐᲕᲣᲨᲕᲐ
--   1. წინაპირობა: 0001..0021 უკვე გაშვებულია (მათ შორის 0021).
--   2. Supabase → SQL Editor → ჩასვი ᲛᲗᲔᲚᲘ ფაილი → RUN.
--   3. რედაქტორი აჩვენებს "შეცდომას" — ეს ნორმალურია, ეს ჩვენი საბოლოო raise-ია:
--        SMOKE OK — rolled back     → ყველა შემოწმება გავიდა, ბაზა ხელუხლებელია.
--        SMOKE SKIP: no auth.users row → ბაზაში მომხმარებელი არ არის; ჯერ დარეგისტრირდი.
--        SMOKE FAIL: <შემოწმება>: expected X got Y → ეს კონკრეტული წესი დარღვეულია.
--
-- ᲠᲐ ᲒᲐᲓᲐᲛᲝᲬᲛᲓᲔᲑᲐ (ნომრები = შეტყობინებებში)
--    1  B-1: `new` სტატუსით შექმნილი შეკვეთა მარაგს არ ეხება
--    2  new -> processing აკლებს შეკვეთილ რაოდენობას
--    3  processing -> cancelled აბრუნებს
--    4  new -> cancelled მარაგს არ ეხება
--    5  F-06: cancelled -> processing ისევ აკლებს
--    6  processing -> done და done -> processing მარაგს არ ეხება; done -> cancelled აბრუნებს
--    7  არასაკმარისი მარაგი: INSUFFICIENT_STOCK, სტატუსიც და მარაგიც უცვლელი
--    8  არასწორი p_expected_old: STATUS_CHANGED, არაფერი იცვლება
--    9  სხვა shop_id: ORDER_NOT_FOUND
--   10  წაშლილი/არარსებული პროდუქტი items-ში გამოტოვება (შეცდომის გარეშე)
--   11  ორი პროდუქტი, ერთი არასაკმარისი: არც ერთი არ იკლებს (ატომურობა)
--   12  EXECUTE უფლებები: authenticated/anon = false, service_role = true
--
-- ᲗᲣ SMOKE FAIL
--   გაჩერდი, deploy-ს ნუ გააგრძელებ. დააკოპირე სრული შეტყობინება დეველოპერს
--   (ან Claude-ს). ბაზაში არაფერი დარჩენილა, ამიტომ ტესტის გამეორება უსაფრთხოა.
--   თუ შეტყობინება არ იწყება 'SMOKE'-ით (მაგ. not-null / check constraint /
--   function does not exist), ესეც წარუმატებლობაა: ან 0021 არ არის გაშვებული, ან
--   სქემა შეიცვალა და fixture-ის INSERT-ები განახლებას საჭიროებს. ესეც rollback-დება.
--
-- ⚠️ ეს ფაილი ავტორმა არ გაუშვია (არც ლოკალურად, არც remote-ზე) — პირველი გაშვება მფლობელისაა.
-- ============================================================================

do $$
declare
  v_user uuid;
  v_shop uuid;
  v_p1   uuid;
  v_p2   uuid;
  v_ghost uuid := gen_random_uuid();  -- არარსებული პროდუქტის id (check 10)
  v_o    uuid;                        -- მიმდინარე შეკვეთა
  v_o1   uuid;                        -- მთავარი შეკვეთა (checks 1-6)
  v_res  jsonb;
  v_err  text;
  v_q1   int;
  v_q2   int;
  v_st   text;
begin
  -- ---- fixtures -------------------------------------------------------------
  select id into v_user from auth.users limit 1;
  if v_user is null then
    raise exception 'SMOKE SKIP: no auth.users row';
  end if;

  insert into public.shops (owner_id, name)
    values (v_user, '__SMOKE__ shop')
    returning id into v_shop;

  insert into public.products (shop_id, name, price, quantity)
    values (v_shop, '__SMOKE__ p1', 1, 10)
    returning id into v_p1;
  insert into public.products (shop_id, name, price, quantity)
    values (v_shop, '__SMOKE__ p2', 1, 5)
    returning id into v_p2;

  -- ---- 1. B-1: new შეკვეთის შექმნა მარაგს არ ეხება ----------------------------
  insert into public.orders (shop_id, customer_name, items, status)
    values (v_shop, '__SMOKE__ o1',
            jsonb_build_array(jsonb_build_object('product_id', v_p1, 'quantity', 3)),
            'new')
    returning id into v_o1;

  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 1 B-1 new order leaves stock: expected 10 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'new' then
    raise exception 'SMOKE FAIL: 1 B-1 initial status: expected new got %', v_st;
  end if;

  -- ---- 2. new -> processing აკლებს 3-ს -----------------------------------------
  v_res := public.change_order_status(v_o1, v_shop, 'new', 'processing');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 7 then
    raise exception 'SMOKE FAIL: 2 new->processing stock: expected 7 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'processing' then
    raise exception 'SMOKE FAIL: 2 new->processing status: expected processing got %', v_st;
  end if;
  if v_res->>'status' is distinct from 'processing' then
    raise exception 'SMOKE FAIL: 2 returned jsonb status: expected processing got %', v_res->>'status';
  end if;

  -- ---- 3. processing -> cancelled აბრუნებს -------------------------------------
  perform public.change_order_status(v_o1, v_shop, 'processing', 'cancelled');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 3 processing->cancelled stock: expected 10 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'cancelled' then
    raise exception 'SMOKE FAIL: 3 processing->cancelled status: expected cancelled got %', v_st;
  end if;

  -- ---- 4. new -> cancelled მარაგს არ ეხება --------------------------------------
  insert into public.orders (shop_id, customer_name, items, status)
    values (v_shop, '__SMOKE__ o4',
            jsonb_build_array(jsonb_build_object('product_id', v_p1, 'quantity', 3)),
            'new')
    returning id into v_o;
  perform public.change_order_status(v_o, v_shop, 'new', 'cancelled');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 4 new->cancelled stock: expected 10 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o;
  if v_st is distinct from 'cancelled' then
    raise exception 'SMOKE FAIL: 4 new->cancelled status: expected cancelled got %', v_st;
  end if;

  -- ---- 5. F-06: cancelled -> processing ისევ აკლებს ------------------------------
  perform public.change_order_status(v_o1, v_shop, 'cancelled', 'processing');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 7 then
    raise exception 'SMOKE FAIL: 5 F-06 cancelled->processing stock: expected 7 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'processing' then
    raise exception 'SMOKE FAIL: 5 F-06 status: expected processing got %', v_st;
  end if;

  -- ---- 6. processing <-> done უცვლელი; done -> cancelled აბრუნებს -----------------
  perform public.change_order_status(v_o1, v_shop, 'processing', 'done');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 7 then
    raise exception 'SMOKE FAIL: 6 processing->done stock: expected 7 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'done' then
    raise exception 'SMOKE FAIL: 6 processing->done status: expected done got %', v_st;
  end if;

  perform public.change_order_status(v_o1, v_shop, 'done', 'processing');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 7 then
    raise exception 'SMOKE FAIL: 6 done->processing stock: expected 7 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'processing' then
    raise exception 'SMOKE FAIL: 6 done->processing status: expected processing got %', v_st;
  end if;

  perform public.change_order_status(v_o1, v_shop, 'processing', 'done');
  perform public.change_order_status(v_o1, v_shop, 'done', 'cancelled');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 6 done->cancelled stock: expected 10 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o1;
  if v_st is distinct from 'cancelled' then
    raise exception 'SMOKE FAIL: 6 done->cancelled status: expected cancelled got %', v_st;
  end if;

  -- ---- 7. INSUFFICIENT_STOCK: მარაგი 10, შეკვეთა 11 -------------------------------
  insert into public.orders (shop_id, customer_name, items, status)
    values (v_shop, '__SMOKE__ o7',
            jsonb_build_array(jsonb_build_object('product_id', v_p1, 'quantity', 11)),
            'new')
    returning id into v_o;
  v_err := null;
  begin
    perform public.change_order_status(v_o, v_shop, 'new', 'processing');
  exception when others then
    v_err := sqlerrm;
  end;
  if v_err is null or v_err not like 'INSUFFICIENT_STOCK%' then
    raise exception 'SMOKE FAIL: 7 insufficient stock error: expected INSUFFICIENT_STOCK%% got %',
      coalesce(v_err, '(no error)');
  end if;
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 7 stock after failed take: expected 10 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o;
  if v_st is distinct from 'new' then
    raise exception 'SMOKE FAIL: 7 status after failed take: expected new got %', v_st;
  end if;

  -- ---- 8. STATUS_CHANGED: არასწორი p_expected_old --------------------------------
  insert into public.orders (shop_id, customer_name, items, status)
    values (v_shop, '__SMOKE__ o8',
            jsonb_build_array(jsonb_build_object('product_id', v_p1, 'quantity', 2)),
            'new')
    returning id into v_o;
  v_err := null;
  begin
    perform public.change_order_status(v_o, v_shop, 'done', 'processing');
  exception when others then
    v_err := sqlerrm;
  end;
  if v_err is distinct from 'STATUS_CHANGED' then
    raise exception 'SMOKE FAIL: 8 wrong expected_old error: expected STATUS_CHANGED got %',
      coalesce(v_err, '(no error)');
  end if;
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 8 stock after STATUS_CHANGED: expected 10 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o;
  if v_st is distinct from 'new' then
    raise exception 'SMOKE FAIL: 8 status after STATUS_CHANGED: expected new got %', v_st;
  end if;

  -- ---- 9. ORDER_NOT_FOUND: სხვა shop_id ------------------------------------------
  v_err := null;
  begin
    perform public.change_order_status(v_o, gen_random_uuid(), 'new', 'processing');
  exception when others then
    v_err := sqlerrm;
  end;
  if v_err is distinct from 'ORDER_NOT_FOUND' then
    raise exception 'SMOKE FAIL: 9 wrong shop_id error: expected ORDER_NOT_FOUND got %',
      coalesce(v_err, '(no error)');
  end if;
  select quantity into v_q1 from public.products where id = v_p1;
  select status into v_st from public.orders where id = v_o;
  if v_q1 is distinct from 10 or v_st is distinct from 'new' then
    raise exception 'SMOKE FAIL: 9 state after ORDER_NOT_FOUND: expected 10/new got %/%', v_q1, v_st;
  end if;

  -- ---- 10. არარსებული პროდუქტი items-ში გამოტოვება --------------------------------
  insert into public.orders (shop_id, customer_name, items, status)
    values (v_shop, '__SMOKE__ o10',
            jsonb_build_array(
              jsonb_build_object('product_id', v_ghost, 'quantity', 2),
              jsonb_build_object('product_id', v_p1, 'quantity', 3)),
            'new')
    returning id into v_o;
  perform public.change_order_status(v_o, v_shop, 'new', 'processing');  -- არ უნდა ვარდებოდეს
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 7 then
    raise exception 'SMOKE FAIL: 10 take with missing product, real product stock: expected 7 got %', v_q1;
  end if;
  select status into v_st from public.orders where id = v_o;
  if v_st is distinct from 'processing' then
    raise exception 'SMOKE FAIL: 10 take with missing product status: expected processing got %', v_st;
  end if;
  -- დაბრუნებაც არ ვარდება და მხოლოდ რეალურ პროდუქტს აბრუნებს
  perform public.change_order_status(v_o, v_shop, 'processing', 'cancelled');
  select quantity into v_q1 from public.products where id = v_p1;
  if v_q1 is distinct from 10 then
    raise exception 'SMOKE FAIL: 10 restore with missing product: expected 10 got %', v_q1;
  end if;

  -- ---- 11. ატომურობა: p1 საკმარისია (2 <= 10), p2 — არა (6 > 5) -------------------
  insert into public.orders (shop_id, customer_name, items, status)
    values (v_shop, '__SMOKE__ o11',
            jsonb_build_array(
              jsonb_build_object('product_id', v_p1, 'quantity', 2),
              jsonb_build_object('product_id', v_p2, 'quantity', 6)),
            'new')
    returning id into v_o;
  v_err := null;
  begin
    perform public.change_order_status(v_o, v_shop, 'new', 'processing');
  exception when others then
    v_err := sqlerrm;
  end;
  if v_err is null or v_err not like 'INSUFFICIENT_STOCK%' then
    raise exception 'SMOKE FAIL: 11 atomicity error: expected INSUFFICIENT_STOCK%% got %',
      coalesce(v_err, '(no error)');
  end if;
  select quantity into v_q1 from public.products where id = v_p1;
  select quantity into v_q2 from public.products where id = v_p2;
  if v_q1 is distinct from 10 or v_q2 is distinct from 5 then
    raise exception 'SMOKE FAIL: 11 atomicity stock p1/p2: expected 10/5 got %/%', v_q1, v_q2;
  end if;
  select status into v_st from public.orders where id = v_o;
  if v_st is distinct from 'new' then
    raise exception 'SMOKE FAIL: 11 atomicity status: expected new got %', v_st;
  end if;

  -- ---- 12. EXECUTE უფლებები ---------------------------------------------------------
  if has_function_privilege('authenticated', 'public.change_order_status(uuid,uuid,text,text)', 'EXECUTE') then
    raise exception 'SMOKE FAIL: 12 authenticated EXECUTE: expected false got true';
  end if;
  if has_function_privilege('anon', 'public.change_order_status(uuid,uuid,text,text)', 'EXECUTE') then
    raise exception 'SMOKE FAIL: 12 anon EXECUTE: expected false got true';
  end if;
  if not has_function_privilege('service_role', 'public.change_order_status(uuid,uuid,text,text)', 'EXECUTE') then
    raise exception 'SMOKE FAIL: 12 service_role EXECUTE: expected true got false';
  end if;

  -- ---- ბოლო: ყოველთვის raise -> მთელი ტრანზაქცია უქმდება --------------------------
  raise exception 'SMOKE OK — rolled back';
end;
$$;
