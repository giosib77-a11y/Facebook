-- ============================================================================
-- 0031: orders.idempotency_key — საჯარო შეკვეთის განმეორებამ მეორე შეკვეთა არ შექმნას (A-020)
--
-- დანიშნულება
-- შესაკვეთი ფორმა (`OrderPage`) ერთ შევსებაზე ერთ UUID-ს ქმნის და `POST /orders`-ს უგზავნის.
-- თუ სერვერმა შეკვეთა ჩაწერა, მაგრამ პასუხი გზაში დაიკარგა და მყიდველი ხელახლა აგზავნის, backend
-- `(shop_id, idempotency_key)`-ით არსებულ შეკვეთას პოულობს და მას აბრუნებს. unique index-ი
-- ერთდროულ ორ მოთხოვნასაც ფარავს (მეორე INSERT 23505-ით ვარდება → backend არსებულს აბრუნებს).
-- nullable: ძველი შეკვეთები და key-ის გარეშე მოთხოვნები (ძველი ქეშირებული ფორმა) — როგორც აქამდე.
--
-- უსაფრთხოება
-- ჩაწერა მხოლოდ backend-იდან (service_role; `orders`-ზე INSERT/UPDATE `authenticated`-ს 0018/0022-ით
-- არ აქვს). ამიტომ ამ ფაილში არც უფლების მიცემაა, არც ჩამორთმევა, არც პოლისი.
--
-- ⚠️ გაუშვი backend deploy-მდე (რეკომენდებული). backend სვეტის გარეშეც მუშაობს: შეკვეთა იქმნება
--    idempotency-ს გარეშე (ძველი ქცევა), ლოგში WARNING.
--
-- იდემპოტენტურია (add column if not exists / create unique index if not exists).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.orders
  add column if not exists idempotency_key uuid;

create unique index if not exists orders_shop_idempotency_key_uniq
  on public.orders (shop_id, idempotency_key)
  where idempotency_key is not null;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select data_type, is_nullable from information_schema.columns
--   where table_schema = 'public' and table_name = 'orders' and column_name = 'idempotency_key';
--   -- სწორი შედეგი: uuid, YES
--
--   select indexdef from pg_indexes
--   where schemaname = 'public' and indexname = 'orders_shop_idempotency_key_uniq';
--   -- სწორი შედეგი: CREATE UNIQUE INDEX ... (shop_id, idempotency_key) WHERE (idempotency_key IS NOT NULL)
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; backend idempotency-ს გარეშე გააგრძელებს):
--   drop index if exists public.orders_shop_idempotency_key_uniq;
--   alter table public.orders drop column if exists idempotency_key;
-- ============================================================================
