-- ============================================================================
-- 0032: create_shop_limited — მაღაზიის ლიმიტის შემოწმება და INSERT ერთ ტრანზაქციაში (A-029)
--
-- დანიშნულება
-- `POST /shops` აქამდე ჯერ ითვლიდა მფლობელის მაღაზიებს, მერე ცალკე მოთხოვნით ამატებდა ახალს.
-- ორი ერთდროული მოთხოვნა ორივე შემოწმებას გადიოდა და ლიმიტზე მეტი მაღაზია იქმნებოდა
-- (მაგ. free — 1 მაღაზია, მაგრამ ორი პარალელური მოთხოვნით 2). ეს ფუნქცია მფლობელის მიხედვით
-- advisory lock-ს იღებს (ტრანზაქციის ბოლომდე), ითვლის და ამატებს — ორივე ერთ ტრანზაქციაში,
-- ამიტომ მეორე მოთხოვნა პირველის დასრულებას დაელოდება და ლიმიტზე `shop_limit_reached`-ს მიიღებს.
-- `p_limit = null` — ულიმიტო პაკეტი (შემოწმება გამოტოვებულია, INSERT მაინც ეშვება).
-- ლიმიტს ითვლის და გადასცემს backend (`owner_shop_limit`); ფუნქცია მხოლოდ ატომურობას უზრუნველყოფს.
--
-- უსაფრთხოება
-- SECURITY DEFINER, `set search_path = public`. `p_owner`-ს აწვდის მხოლოდ backend (service_role)
-- ავტორიზებული მომხმარებლის id-ით, ამიტომ EXECUTE `public` / `anon` / `authenticated`-ს ჩამორთმეულია
-- და ენიჭება მხოლოდ `service_role`-ს. გამყიდველს INSERT `shops`-ზე 0015-ით ისედაც არ აქვს.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). backend მის გარეშეც მუშაობს: ფუნქციის არქონისას
--    (PGRST202) ძველ გზაზე გადადის — ლიმიტის შემოწმება და INSERT ცალ-ცალკე, ლოგში ერთჯერადი WARNING.
--
-- იდემპოტენტურია (create or replace function; revoke / grant განმეორებით უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

create or replace function public.create_shop_limited(
  p_owner       uuid,
  p_name        text,
  p_description text,
  p_currency    text,
  p_tier        text,
  p_limit       int
)
returns setof public.shops
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.shops;
begin
  -- ერთი მფლობელის პარალელური გამოძახებები რიგდება (lock ტრანზაქციის ბოლოს თავისით იხსნება)
  perform pg_advisory_xact_lock(hashtextextended('create_shop:' || p_owner::text, 0));

  if p_limit is not null
     and (select count(*) from public.shops where owner_id = p_owner) >= p_limit then
    raise exception 'shop_limit_reached' using errcode = 'P0001';
  end if;

  -- INSERT ... RETURNING INTO + RETURN NEXT — ყველა PG ვერსიაზე ვალიდურია (RETURN QUERY + DML ძველზე ვარდება)
  insert into public.shops (owner_id, name, description, currency, subscription_tier)
  values (p_owner, p_name, p_description, p_currency, p_tier)
  returning * into v_row;
  return next v_row;
  return;
end
$$;

revoke execute on function public.create_shop_limited(uuid, text, text, text, text, int)
  from public, anon, authenticated;
grant execute on function public.create_shop_limited(uuid, text, text, text, text, int)
  to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select has_function_privilege('authenticated', 'public.create_shop_limited(uuid,text,text,text,text,int)', 'EXECUTE');
--   -- სწორი შედეგი: f
--   select has_function_privilege('service_role', 'public.create_shop_limited(uuid,text,text,text,text,int)', 'EXECUTE');
--   -- სწორი შედეგი: t
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; backend ძველ გზაზე გააგრძელებს):
--   drop function if exists public.create_shop_limited(uuid, text, text, text, text, int);
-- ============================================================================
