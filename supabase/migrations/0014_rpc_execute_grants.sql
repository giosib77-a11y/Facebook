-- ============================================================================
-- 0014: RPC-ების EXECUTE ნებართვები (უსაფრთხოება — P0-1)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- `track_bot_customer` არის SECURITY DEFINER (0004), ე.ი. RLS-ს გვერდს უვლის.
-- Postgres ახლად შექმნილ ფუნქციაზე EXECUTE-ს ავტომატურად აძლევს PUBLIC-ს, ჩვენს
-- მიგრაციებში კი არც ერთი REVOKE არ ყოფილა. შედეგად ფუნქცია გამოძახებადი იყო
-- `anon` როლიდან, PostgREST-ის /rest/v1/rpc/-ით.
--
-- დადასტურებული ემპირიულად (2026-08-23): anon გასაღებით გამოძახებამ დააბრუნა
-- HTTP 409 / 23503 — ანუ შეცდომა INSERT-ის მომენტში მოვიდა, არა ავტორიზაციაზე.
-- ფუნქცია სრულდებოდა; მხოლოდ განზრახ არარსებულ shop_id-ს დაეჯახა.
--
-- ᲗᲐᲕᲓᲐᲡᲮᲛᲐ
-- anon გასაღები საჯაროა (config.js), shop_id საჯაროა (order.html?shop=…).
-- სკრიპტი იძახებს track_bot_customer-ს ყოველ ჯერზე ახალი p_psid-ით →
-- bot_customers ივსება ყალბი მწკრივებით → monthly_unique აჭარბებს პაკეტის
-- ლიმიტს → webhook.py-ში over_limit=True → ᲑᲝᲢᲘ ᲬᲧᲕᲔᲢᲡ ᲞᲐᲡᲣᲮᲡ ᲠᲔᲐᲚᲣᲠ ᲙᲚᲘᲔᲜᲢᲔᲑᲖᲔ.
-- უფასო მაღაზიის გასათიშად საკმარისია 31 მოთხოვნა.
--
-- ⚠️ ჩვენი აპლიკაციური rate limiter ამას ვერ ხედავს — მოთხოვნა პირდაპირ
--    Supabase-ს მიდის და ჩვენს backend-ს საერთოდ არ ეხება.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- სამივე RPC-ს ვურთმევთ EXECUTE-ს PUBLIC/anon/authenticated-ისგან და ვაძლევთ
-- მხოლოდ service_role-ს. backend ისედაც მხოლოდ service_role-ით იძახებს:
--   webhook.py:170          → track_bot_customer  (get_service_client)
--   orders.py               → decrement_stock     (sc = get_service_client)
--   orders.py               → apply_stock_delta   (get_service_client)
--
-- 🚫 set_updated_at ᲘᲒᲜᲝᲠᲘᲠᲔᲑᲣᲚᲘᲐ ᲒᲐᲜᲖᲠᲐᲮ — ის trigger-ფუნქციაა, არა RPC.
--    PostgREST trigger-ის დამბრუნებელ ფუნქციებს არ ავრცელებს /rpc/-ზე, ხოლო
--    მისგან EXECUTE-ის წართმევა PUBLIC-ს ჩვეულებრივ INSERT/UPDATE-ს გატეხავდა.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

do $$
declare
  f record;
  n int := 0;
begin
  for f in
    select p.oid::regprocedure as sig
      from pg_proc p
      join pg_namespace ns on ns.oid = p.pronamespace
     where ns.nspname = 'public'
       and p.proname in ('track_bot_customer', 'decrement_stock', 'apply_stock_delta')
  loop
    -- regprocedure ხელმოწერას ტიპებთან ერთად იძლევა → overload-იც სწორად დამუშავდება
    execute format('revoke execute on function %s from public, anon, authenticated', f.sig);
    execute format('grant  execute on function %s to service_role', f.sig);
    n := n + 1;
    raise notice 'დაიხურა: %', f.sig;
  end loop;

  if n = 0 then
    raise exception 'არც ერთი ფუნქცია ვერ მოიძებნა — მიგრაციები 0004/0009/0013 გაშვებულია?';
  end if;
  raise notice 'სულ დამუშავდა % ფუნქცია', n;
end $$;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select p.proname,
--          p.prosecdef as security_definer,
--          coalesce(array_to_string(p.proacl, E'\n'), '(ნაგულისხმევი = PUBLIC-საც აქვს!)') as acl
--     from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
--    where ns.nspname = 'public'
--      and p.proname in ('track_bot_customer','decrement_stock','apply_stock_delta');
--
-- სწორი შედეგი: acl-ში მხოლოდ მფლობელი და `service_role=X/…` ჩანს.
-- ᲐᲠ ᲣᲜᲓᲐ ᲘᲧᲝᲡ:  `=X/…` (ეს PUBLIC-ია), `anon=X/…`, `authenticated=X/…`
--
-- ცოცხალი შემოწმება: anon გასაღებით /rest/v1/rpc/track_bot_customer →
--   მოსალოდნელი 403 (42501). ⚠️ 409/23503 ᲜᲘᲨᲜᲐᲕᲡ, ᲠᲝᲛ ᲒᲐᲡᲬᲝᲠᲔᲑᲐ ᲐᲠ ᲘᲛᲣᲨᲐᲕᲐ.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ᲡᲘᲡᲢᲔᲛᲣᲠᲘ ᲜᲐᲬᲘᲚᲘ — ᲒᲐᲜᲖᲠᲐᲮ ᲐᲠ ᲐᲠᲘᲡ ᲩᲐᲠᲗᲣᲚᲘ
--
-- ქვემოთ ბრძანება მომავალში შექმნილ ფუნქციებს ავტომატურად დახურავდა, ე.ი.
-- იგივე შეცდომა აღარ განმეორდებოდა:
--
--   alter default privileges in schema public
--     revoke execute on functions from public, anon, authenticated;
--
-- ᲠᲐᲢᲝᲛ ᲐᲠ ᲒᲕᲘᲨᲕᲘᲐ ᲐᲮᲚᲐ: ეს მოქმედებს ყველა მომავალ ფუნქციაზე, რომელსაც ეს
-- როლი შექმნის — მათ შორის Supabase-ის გაფართოებების/dashboard-ის მიერ
-- შექმნილზეც. ჯერ ძირითადი გასწორება და დაკვირვება, მერე ეს.
-- ----------------------------------------------------------------------------
