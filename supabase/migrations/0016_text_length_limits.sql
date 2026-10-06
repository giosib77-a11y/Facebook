-- ============================================================================
-- 0016: ტექსტური სვეტების სიგრძის ლიმიტები (FA-01)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- 0015-ის შემდეგ `authenticated` კვლავ წერს shops(name, description, currency,
-- knowledge, knowledge_filename) და products(name, description, sku, image_url)
-- სვეტებში პირდაპირ PostgREST-ით — backend-ის Pydantic შემოწმებების გვერდის
-- ავლით. სიგრძის შეზღუდვა ბაზაში არ იყო: გამყიდველს შეეძლო მრავალმეგაბაიტიანი
-- ტექსტის ჩაწერა, რომელიც ბოტის prompt-ში მთლიანად ხვდებოდა (ხარჯი, timeout,
-- prompt injection-ის ზედაპირი). orders-ის ველები (მისამართი, შენიშვნა, items)
-- კლიენტის მიერ შევსებადია და ასევე შეუზღუდავი იყო.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- CHECK constraint-ები სიმბოლოებში (char_length; NULL დასაშვებია):
--   shops     name 200, description 2000, currency 8, knowledge 21000,
--             knowledge_filename 255
--   products  name 200, description 5000, sku 100, image_url 2048
--   orders    customer_name 120, customer_phone 40, customer_address 500,
--             note 1000; items — JSON მასივი, მაქს. 100 ელემენტი
-- API (Pydantic) იგივე ლიმიტებს იყენებს; ბოტის prompt დამატებით ჭრის (bot.py).
--
-- ⚠️ ჯერ გაუშვი PRE-CHECK. თუ რომელიმე over-ის რიცხვი > 0, ADD CONSTRAINT
--    ჩავარდება — ჯერ ის მწკრივები გაასწორე.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (გაუშვი ცალკე, მიგრაციამდე). სწორი შედეგი: ყველა over = 0.
--
--   select 'shops.name' as col, max(char_length(name)) as max_len,
--          count(*) filter (where char_length(name) > 200) as over from public.shops
--   union all select 'shops.description', max(char_length(description)),
--          count(*) filter (where char_length(description) > 2000) from public.shops
--   union all select 'shops.currency', max(char_length(currency)),
--          count(*) filter (where char_length(currency) > 8) from public.shops
--   union all select 'shops.knowledge', max(char_length(knowledge)),
--          count(*) filter (where char_length(knowledge) > 21000) from public.shops
--   union all select 'shops.knowledge_filename', max(char_length(knowledge_filename)),
--          count(*) filter (where char_length(knowledge_filename) > 255) from public.shops
--   union all select 'products.name', max(char_length(name)),
--          count(*) filter (where char_length(name) > 200) from public.products
--   union all select 'products.description', max(char_length(description)),
--          count(*) filter (where char_length(description) > 5000) from public.products
--   union all select 'products.sku', max(char_length(sku)),
--          count(*) filter (where char_length(sku) > 100) from public.products
--   union all select 'products.image_url', max(char_length(image_url)),
--          count(*) filter (where char_length(image_url) > 2048) from public.products
--   union all select 'orders.customer_name', max(char_length(customer_name)),
--          count(*) filter (where char_length(customer_name) > 120) from public.orders
--   union all select 'orders.customer_phone', max(char_length(customer_phone)),
--          count(*) filter (where char_length(customer_phone) > 40) from public.orders
--   union all select 'orders.customer_address', max(char_length(customer_address)),
--          count(*) filter (where char_length(customer_address) > 500) from public.orders
--   union all select 'orders.note', max(char_length(note)),
--          count(*) filter (where char_length(note) > 1000) from public.orders
--   union all select 'orders.items',
--          max(case when jsonb_typeof(items) = 'array' then jsonb_array_length(items) end),
--          count(*) filter (where jsonb_typeof(items) <> 'array'
--                              or (jsonb_typeof(items) = 'array' and jsonb_array_length(items) > 100))
--          from public.orders;
-- ----------------------------------------------------------------------------

begin;

-- shops
alter table public.shops drop constraint if exists shops_name_len_chk;
alter table public.shops add constraint shops_name_len_chk check (char_length(name) <= 200);
alter table public.shops drop constraint if exists shops_description_len_chk;
alter table public.shops add constraint shops_description_len_chk check (char_length(description) <= 2000);
alter table public.shops drop constraint if exists shops_currency_len_chk;
alter table public.shops add constraint shops_currency_len_chk check (char_length(currency) <= 8);
alter table public.shops drop constraint if exists shops_knowledge_len_chk;
alter table public.shops add constraint shops_knowledge_len_chk check (char_length(knowledge) <= 21000);
alter table public.shops drop constraint if exists shops_knowledge_filename_len_chk;
alter table public.shops add constraint shops_knowledge_filename_len_chk check (char_length(knowledge_filename) <= 255);

-- products
alter table public.products drop constraint if exists products_name_len_chk;
alter table public.products add constraint products_name_len_chk check (char_length(name) <= 200);
alter table public.products drop constraint if exists products_description_len_chk;
alter table public.products add constraint products_description_len_chk check (char_length(description) <= 5000);
alter table public.products drop constraint if exists products_sku_len_chk;
alter table public.products add constraint products_sku_len_chk check (char_length(sku) <= 100);
alter table public.products drop constraint if exists products_image_url_len_chk;
alter table public.products add constraint products_image_url_len_chk check (char_length(image_url) <= 2048);

-- orders
alter table public.orders drop constraint if exists orders_customer_name_len_chk;
alter table public.orders add constraint orders_customer_name_len_chk check (char_length(customer_name) <= 120);
alter table public.orders drop constraint if exists orders_customer_phone_len_chk;
alter table public.orders add constraint orders_customer_phone_len_chk check (char_length(customer_phone) <= 40);
alter table public.orders drop constraint if exists orders_customer_address_len_chk;
alter table public.orders add constraint orders_customer_address_len_chk check (char_length(customer_address) <= 500);
alter table public.orders drop constraint if exists orders_note_len_chk;
alter table public.orders add constraint orders_note_len_chk check (char_length(note) <= 1000);
alter table public.orders drop constraint if exists orders_items_len_chk;
alter table public.orders add constraint orders_items_len_chk
  check (jsonb_typeof(items) = 'array' and jsonb_array_length(items) <= 100);

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select conrelid::regclass as tbl, conname
--   from pg_constraint
--   where conname like '%\_len\_chk' escape '\'
--     and conrelid in ('public.shops'::regclass, 'public.products'::regclass,
--                      'public.orders'::regclass)
--   order by 1, 2;
--
-- სწორი შედეგი: 14 მწკრივი (shops 5, products 4, orders 5).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK
--
-- ⚠️ ამის შემდეგ ბაზა ისევ შეუზღუდავ ტექსტს მიიღებს პირდაპირ PostgREST-ით.
--    backend-ის კოდს rollback არ სჭირდება — Pydantic/prompt ლიმიტები რჩება.
--
--   begin;
--   alter table public.shops    drop constraint if exists shops_name_len_chk;
--   alter table public.shops    drop constraint if exists shops_description_len_chk;
--   alter table public.shops    drop constraint if exists shops_currency_len_chk;
--   alter table public.shops    drop constraint if exists shops_knowledge_len_chk;
--   alter table public.shops    drop constraint if exists shops_knowledge_filename_len_chk;
--   alter table public.products drop constraint if exists products_name_len_chk;
--   alter table public.products drop constraint if exists products_description_len_chk;
--   alter table public.products drop constraint if exists products_sku_len_chk;
--   alter table public.products drop constraint if exists products_image_url_len_chk;
--   alter table public.orders   drop constraint if exists orders_customer_name_len_chk;
--   alter table public.orders   drop constraint if exists orders_customer_phone_len_chk;
--   alter table public.orders   drop constraint if exists orders_customer_address_len_chk;
--   alter table public.orders   drop constraint if exists orders_note_len_chk;
--   alter table public.orders   drop constraint if exists orders_items_len_chk;
--   commit;
-- ----------------------------------------------------------------------------
