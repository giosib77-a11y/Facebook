-- ============================================================================
-- 0021: შეკვეთის სტატუსი + მარაგი ერთ DB ტრანზაქციაში (S11-1, აუდიტი #2)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- backend-ის `update_order_status` სტატუსსა და მარაგს ცალ-ცალკე ცვლიდა:
-- (1) decrement_stock → (2) UPDATE orders → (3) apply_stock_delta(+1).
-- თუ სტატუსი უკვე შეიცვალა (processing/done → cancelled), მაგრამ მარაგის
-- დაბრუნება (3) ჩავარდა, შეკვეთა გაუქმებულია, მარაგი კი დაკარგული რჩება და
-- მომხმარებელი 500-ს იღებს.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- ფუნქცია `public.change_order_status(order, shop, expected_old, new)` — ერთი
-- plpgsql გამოძახება = ერთი ტრანზაქცია: შეკვეთის მწკრივს ბლოკავს (FOR UPDATE),
-- ამოწმებს shop_id-სა და მოსალოდნელ ძველ სტატუსს, მარაგის წესს ასრულებს
-- (დაკავებულ processing/done-ზე გადასვლა → decrement_stock; გასვლა →
-- apply_stock_delta(+1); `new` მარაგს არ ეხება) და სტატუსს აახლებს. ნებისმიერი
-- შეცდომა ყველაფერს აბრუნებს. მარაგი ისევ ერთადერთ წესზეა: იკლებს მხოლოდ
-- new/cancelled → processing/done-ზე.
-- შეცდომის კოდები (RAISE EXCEPTION-ის message):
--   ORDER_NOT_FOUND, STATUS_CHANGED, INVALID_STATUS,
--   INSUFFICIENT_STOCK|<სახელი>|<დარჩენილი>, PRODUCT_NOT_FOUND (decrement_stock-იდან).
--
-- SECURITY INVOKER (ნაგულისხმევი); ეძახის მხოლოდ backend service_role-ით, მფლობელობა
-- კი წინასწარ შემოწმებულია მომხმარებლის JWT-ით (RLS). EXECUTE მხოლოდ service_role-ს.
--
-- გაშვების რიგი: ჯერ ეს მიგრაცია, მერე backend-ის deploy. ძველი backend ამ ფუნქციას
-- არ იძახებს, ამიტომ 0021 მასთან უსაფრთხოა (დამატებითია). ახალი backend 0021-ის გარეშე
-- სტატუსის შეცვლაზე 500-ს დააბრუნებს (ფუნქცია არ არსებობს) — არაფერი იცვლება.
-- დამოკიდებულია: 0009 (decrement_stock), 0013 (apply_stock_delta).
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია (create or replace).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (გაუშვი ცალკე, მიგრაციამდე). სწორი შედეგი: ორივე ფუნქცია არსებობს (2 მწკრივი).
--
--   select proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--    where n.nspname = 'public' and proname in ('decrement_stock', 'apply_stock_delta');
-- ----------------------------------------------------------------------------

begin;

create or replace function public.change_order_status(
  p_order_id     uuid,
  p_shop_id      uuid,
  p_expected_old text,
  p_new          text
)
returns jsonb
language plpgsql
as $$
declare
  v_order public.orders%rowtype;
  v_items jsonb;
  v_was_held boolean;
  v_now_held boolean;
begin
  if p_new is null or p_new not in ('new', 'processing', 'done', 'cancelled') then
    raise exception 'INVALID_STATUS';
  end if;

  -- შეკვეთის ჩაკეტვა: პარალელური შეცვლა ელოდება და მერე STATUS_CHANGED-ს მიიღებს
  select * into v_order
    from public.orders
   where id = p_order_id and shop_id = p_shop_id
   for update;

  if not found then
    raise exception 'ORDER_NOT_FOUND';
  end if;

  if v_order.status is distinct from p_expected_old then
    raise exception 'STATUS_CHANGED';
  end if;

  v_was_held := v_order.status in ('processing', 'done');
  v_now_held := p_new in ('processing', 'done');

  if v_now_held and not v_was_held then
    -- დაკავება: მხოლოდ არსებული პროდუქტები (წაშლილს ვტოვებთ, როგორც ადრე), ჯამდება
    -- product_id-ით, დალაგებულია (ერთნაირი lock-ის რიგი → deadlock-ის რისკი მცირდება)
    select coalesce(jsonb_agg(jsonb_build_object('product_id', t.pid, 'quantity', t.q)
                              order by t.pid), '[]'::jsonb)
      into v_items
      from (
        select (e->>'product_id')::uuid as pid, sum((e->>'quantity')::int) as q
          from jsonb_array_elements(coalesce(v_order.items, '[]'::jsonb)) e
         where nullif(e->>'product_id', '') is not null
           and coalesce((e->>'quantity')::int, 0) > 0
         group by 1
      ) t
      join public.products pr on pr.id = t.pid and pr.shop_id = p_shop_id;

    if jsonb_array_length(v_items) > 0 then
      perform public.decrement_stock(p_shop_id, v_items);
    end if;
  elsif v_was_held and not v_now_held then
    -- დაბრუნება (apply_stock_delta თავად ტოვებს ცუდ/ცარიელ ჩანაწერებს)
    perform public.apply_stock_delta(p_shop_id, coalesce(v_order.items, '[]'::jsonb), 1);
  end if;

  update public.orders
     set status = p_new
   where id = p_order_id
  returning * into v_order;

  return to_jsonb(v_order);
end;
$$;

revoke execute on function public.change_order_status(uuid, uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.change_order_status(uuid, uuid, text, text)
  to service_role;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select p.proname,
--          p.prosecdef as security_definer,
--          coalesce(array_to_string(p.proacl, E'\n'), '(PUBLIC-საც აქვს!)') as acl
--     from pg_proc p join pg_namespace ns on ns.oid = p.pronamespace
--    where ns.nspname = 'public' and p.proname = 'change_order_status';
--
-- სწორი შედეგი: 1 მწკრივი, security_definer = false, acl-ში `service_role=X/…`
-- და მფლობელი; ᲐᲠ ᲣᲜᲓᲐ ᲘᲧᲝᲡ `=X/…` (PUBLIC), `anon=X/…`, `authenticated=X/…`.
--
-- ფუნქციური შემოწმება (მხოლოდ სატესტო მაღაზიაზე!): ერთი new შეკვეთა ერთი პროდუქტით →
--   select public.change_order_status('<order_id>', '<shop_id>', 'new', 'processing');
--   → პროდუქტის quantity შემცირდა შეკვეთის რაოდენობით, status = processing;
--   select public.change_order_status('<order_id>', '<shop_id>', 'processing', 'cancelled');
--   → quantity დაბრუნდა; განმეორებით 'processing'-ის მოლოდნელით → STATUS_CHANGED.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK (ახალი backend-ის დაბრუნების შემდეგ; ძველი backend ფუნქციას არ იყენებს)
--
--   begin;
--   drop function if exists public.change_order_status(uuid, uuid, text, text);
--   commit;
-- ----------------------------------------------------------------------------
