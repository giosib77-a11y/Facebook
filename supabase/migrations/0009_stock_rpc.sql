-- ============================================================================
-- 0009: მარაგის ატომური დაკლება (race condition-ის თავიდან ასაცილებლად)
--
-- პრობლემა: შეკვეთისას მარაგი „წაიკითხე → შეამოწმე → ჩაწერე"-თ იკლებდა.
-- ორი ერთდროული შეკვეთა ერთსა და იმავე ბოლო ცალზე → ორივე გაივლიდა →
-- ზედმეტი გაყიდვა (overselling).
--
-- გამოსავალი: ერთი ატომური UPDATE availability-შემოწმებით. ბაზა თვითონ
-- ასერიულებს (row lock) — მეორე ერთდროული მოთხოვნა ვერ გაივლის.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია (create or replace).
-- ============================================================================

create or replace function public.decrement_stock(p_shop_id uuid, p_items jsonb)
returns void
language plpgsql
as $$
declare
  item   jsonb;
  v_pid  uuid;
  v_qty  int;
  v_name text;
  v_avail int;
begin
  for item in select * from jsonb_array_elements(p_items)
  loop
    v_pid := (item->>'product_id')::uuid;
    v_qty := coalesce((item->>'quantity')::int, 0);

    if v_qty <= 0 then
      raise exception 'INVALID_QTY';
    end if;

    -- ატომური დაკლება: მხოლოდ თუ საკმარისი მარაგია (row lock ერთდროულობაზე)
    update public.products
       set quantity = quantity - v_qty
     where id = v_pid and shop_id = p_shop_id and quantity >= v_qty;

    if not found then
      -- ვერ დაიკლო: ან პროდუქტი არ არსებობს, ან მარაგი არ ჰყოფნის
      select name, quantity into v_name, v_avail
        from public.products
       where id = v_pid and shop_id = p_shop_id;

      if v_name is null then
        raise exception 'PRODUCT_NOT_FOUND';
      else
        -- ფორმატი: INSUFFICIENT_STOCK|<სახელი>|<დარჩენილი>
        raise exception 'INSUFFICIENT_STOCK|%|%', v_name, v_avail;
      end if;
    end if;
  end loop;
end;
$$;

-- ============================================================================
-- შემოწმება: SQL Editor-ში —
--   select public.decrement_stock('<shop_id>', '[{"product_id":"<id>","quantity":1}]');
-- საკმარისი მარაგი → წარმატება; მეტი რაოდენობა → INSUFFICIENT_STOCK|... შეცდომა.
-- ============================================================================
