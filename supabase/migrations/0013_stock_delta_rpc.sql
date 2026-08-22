-- ============================================================================
-- 0013: მარაგის ატომური კორექცია (გაუქმება / დაბრუნება / კომპენსაცია)
--
-- პრობლემა (კოდ-რევიუ P1-5): მიგრაცია 0009-მა შეკვეთის *შექმნის* გზა გაასწორა
-- (decrement_stock), მაგრამ დანარჩენი სამი გზა ისევ „წაიკითხე → გამოთვალე →
-- ჩაწერე"-ს იყენებდა backend-ში (_apply_stock_delta):
--   1. შეკვეთა ვერ ჩაიწერა → მარაგის დაბრუნება
--   2. შეკვეთის გაუქმება   → მარაგის დაბრუნება
--   3. გაუქმებულის ხელახლა გახსნა → მარაგის გამოკლება
-- ორი ერთდროული კორექცია ერთმანეთს გადააწერდა და ერთი იკარგებოდა.
--
-- გამოსავალი: კორექცია ერთი ატომური UPDATE-ით, ბაზის row-lock-ის ქვეშ.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია (create or replace).
-- ⚠️ backend მუშაობს ამ მიგრაციის გარეშეც — თუ ფუნქცია არ არსებობს, ძველ
--    (არა-ატომურ) გზაზე გადადის. ანუ deploy-ის რიგითობა მნიშვნელობა არ აქვს.
-- ============================================================================

create or replace function public.apply_stock_delta(
  p_shop_id uuid,
  p_items   jsonb,
  p_sign    int
)
returns void
language plpgsql
as $$
declare
  item  jsonb;
  v_pid uuid;
  v_qty int;
begin
  if p_sign not in (-1, 1) then
    raise exception 'INVALID_SIGN';
  end if;

  for item in select * from jsonb_array_elements(p_items)
  loop
    v_pid := (item->>'product_id')::uuid;
    v_qty := coalesce((item->>'quantity')::int, 0);

    -- არასწორ/ცარიელ ჩანაწერს ვტოვებთ (კომპენსაცია არ უნდა გაიჭედოს ერთ ცუდ ელემენტზე)
    if v_pid is null or v_qty <= 0 then
      continue;
    end if;

    -- ატომური კორექცია. greatest(0, …) — მარაგი მინუსში არ ჩავარდება
    -- (იგივე ქცევა, რაც backend-ის ძველ _apply_stock_delta-ს ჰქონდა).
    -- დუბლირებული product_id ერთსა და იმავე შეკვეთაში სწორად ჯამდება,
    -- რადგან თითო ჩანაწერზე ცალკე UPDATE სრულდება.
    update public.products
       set quantity = greatest(0, quantity + p_sign * v_qty)
     where id = v_pid and shop_id = p_shop_id;
  end loop;
end;
$$;

-- ============================================================================
-- შემოწმება (სატესტო მაღაზიაზე!):
--   select public.apply_stock_delta(
--     '<shop_id>', '[{"product_id":"<id>","quantity":2}]'::jsonb, 1);
--   → პროდუქტის quantity უნდა გაიზარდოს 2-ით.
-- ============================================================================
