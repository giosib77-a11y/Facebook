-- ============================================================================
-- check_0014_0016: READ-ONLY შემოწმება — მიგრაციები 0014, 0015, 0016
-- გაშვებულია თუ არა ცოცხალ (live) Supabase ბაზაზე.
--
-- ᲛᲘᲖᲐᲜᲘ: მფლობელი ჩასვამს Supabase → SQL Editor-ში და გაუშვებს (RUN).
-- ᲛᲮᲝᲚᲝᲓ ᲬᲐᲙᲘᲗᲮᲕᲐ: მხოლოდ SELECT + კატალოგი (pg_proc, pg_constraint) და
--   has_*_privilege ფუნქციები. არაფერს ქმნის, არ ცვლის, არ შლის.
--
-- ᲠᲝᲒᲐᲠ ᲬᲐᲘᲙᲘᲗᲮᲝ ᲨᲔᲓᲔᲑᲘ: ერთი ცხრილი, სვეტები migration | check_name | ok | detail.
--   ყველა ok = true  → სამივე მიგრაცია გაშვებულია.
--   რომელიმე ok = false → ამ migration-ის მიგრაცია აკლია ან ნაწილობრივაა
--     გაშვებული (detail გეუბნება რა ნახა). გაუშვი შესაბამისი ფაილი
--     supabase/migrations/-დან (ისინი იდემპოტენტურია).
--   ⚠️ 0016 შენიშვნა: თუ ok=false და ჯერ არ გაგიშვია, მის PRE-CHECK-ს
--     (0016 ფაილის დასაწყისში) გადახედე, სანამ გაუშვებ.
--   ⚠️ თუ ბრძანება შეცდომას აბრუნებს (მაგ. "column does not exist"), ესეც
--     იმის ნიშანია, რომ ბაზის სქემა მოსალოდნელს არ ემთხვევა — მოგვწერე.
-- ============================================================================

select *
from (

  -- --------------------------------------------------------------------------
  -- 0014: სამი RPC დახურულია anon/authenticated/PUBLIC-ისგან, ღიაა service_role-ისთვის
  -- (has_function_privilege('anon', ...) PUBLIC-საც ითვალისწინებს)
  -- --------------------------------------------------------------------------
  select '0014'::text as migration,
         'rpc_locked_down: ' || f.fn as check_name,
         coalesce(p.n > 0 and not p.anon_exec and not p.auth_exec and p.svc_exec, false) as ok,
         case when p.n is null then 'ფუნქცია public სქემაში ვერ მოიძებნა'
              else 'overloads=' || p.n
                   || ' anon=' || p.anon_exec
                   || ' authenticated=' || p.auth_exec
                   || ' service_role=' || p.svc_exec
                   || ' (მოსალოდნელი: f, f, t)'
         end as detail
  from (values ('track_bot_customer'), ('decrement_stock'), ('apply_stock_delta')) as f(fn)
  left join (
    select pr.proname,
           count(*) as n,
           bool_or(has_function_privilege('anon',         pr.oid, 'EXECUTE')) as anon_exec,
           bool_or(has_function_privilege('authenticated', pr.oid, 'EXECUTE')) as auth_exec,
           bool_and(has_function_privilege('service_role', pr.oid, 'EXECUTE')) as svc_exec
    from pg_proc pr
    join pg_namespace ns on ns.oid = pr.pronamespace
    where ns.nspname = 'public'
    group by pr.proname
  ) p on p.proname = f.fn

  union all

  -- --------------------------------------------------------------------------
  -- 0015: ცხრილის/სვეტის დონის ნებართვები shops / products-ზე
  -- --------------------------------------------------------------------------
  select '0015'::text,
         v.name,
         v.actual = v.expected,
         'actual=' || v.actual || ' expected=' || v.expected
  from (values
    ('shops: authenticated table INSERT',              has_table_privilege('authenticated', 'public.shops',    'INSERT'), false),
    ('shops: anon table INSERT',                       has_table_privilege('anon',          'public.shops',    'INSERT'), false),
    ('shops: authenticated table UPDATE',              has_table_privilege('authenticated', 'public.shops',    'UPDATE'), false),
    ('shops: anon table UPDATE',                       has_table_privilege('anon',          'public.shops',    'UPDATE'), false),
    ('shops.subscription_tier column UPDATE',          has_column_privilege('authenticated', 'public.shops', 'subscription_tier',    'UPDATE'), false),
    ('shops.bot_enabled column UPDATE',                has_column_privilege('authenticated', 'public.shops', 'bot_enabled',          'UPDATE'), false),
    ('shops.facebook_page_id column UPDATE',           has_column_privilege('authenticated', 'public.shops', 'facebook_page_id',     'UPDATE'), false),
    ('shops.instagram_account_id column UPDATE',       has_column_privilege('authenticated', 'public.shops', 'instagram_account_id', 'UPDATE'), false),
    ('shops.bot_language column UPDATE (allowed)',     has_column_privilege('authenticated', 'public.shops', 'bot_language',         'UPDATE'), true),
    ('products: authenticated table INSERT',           has_table_privilege('authenticated', 'public.products', 'INSERT'), false),
    ('products: anon table INSERT',                    has_table_privilege('anon',          'public.products', 'INSERT'), false),
    ('products: authenticated table UPDATE',           has_table_privilege('authenticated', 'public.products', 'UPDATE'), false),
    ('products: anon table UPDATE',                    has_table_privilege('anon',          'public.products', 'UPDATE'), false),
    ('products.shop_id column UPDATE',                 has_column_privilege('authenticated', 'public.products', 'shop_id', 'UPDATE'), false),
    ('products.price column UPDATE (allowed)',         has_column_privilege('authenticated', 'public.products', 'price',   'UPDATE'), true)
  ) as v(name, actual, expected)

  union all

  -- --------------------------------------------------------------------------
  -- 0016: 14 *_len_chk CHECK constraint-ი (shops 5, products 4, orders 5)
  -- --------------------------------------------------------------------------
  select '0016'::text,
         'constraint: ' || e.tbl || '.' || e.conname,
         c.oid is not null,
         coalesce(pg_get_constraintdef(c.oid), 'constraint ვერ მოიძებნა')
  from (values
    ('shops',    'shops_name_len_chk'),
    ('shops',    'shops_description_len_chk'),
    ('shops',    'shops_currency_len_chk'),
    ('shops',    'shops_knowledge_len_chk'),
    ('shops',    'shops_knowledge_filename_len_chk'),
    ('products', 'products_name_len_chk'),
    ('products', 'products_description_len_chk'),
    ('products', 'products_sku_len_chk'),
    ('products', 'products_image_url_len_chk'),
    ('orders',   'orders_customer_name_len_chk'),
    ('orders',   'orders_customer_phone_len_chk'),
    ('orders',   'orders_customer_address_len_chk'),
    ('orders',   'orders_note_len_chk'),
    ('orders',   'orders_items_len_chk')
  ) as e(tbl, conname)
  left join pg_constraint c
    on c.conname = e.conname
   and c.conrelid = ('public.' || e.tbl)::regclass

) as checks
order by migration, check_name;
