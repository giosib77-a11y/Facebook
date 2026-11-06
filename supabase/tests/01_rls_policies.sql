-- pgTAP: ცხრილების, RLS-ის და პოლისების ინვენტარი (S24-2, A-042 / N-08).
--
-- რას იცავს: tenant isolation-ის საფუძველს — `public`-ის ყველა ცხრილზე RLS ჩართულია,
-- view / materialized view არ არის (view RLS-ს გვერდს უვლის), და თითოეულ ცხრილზე
-- პოლისების სია ზუსტად ისაა, რაც მიგრაციებიდან გამომდინარეობს.
-- აფიქსირებს მიგრაციებს: 0001 (shops, products, orders), 0018 (orders_delete_own:
-- მხოლოდ done / cancelled), 0024 (upgrade_requests: ur_owner_insert წაიშალა),
-- 0025 (llm_usage), 0029 (data_deletion_requests), 0034 (subscriptions),
-- 0037 (webhook_inbox), 0041 (admin_audit_log).
-- backend-only ცხრილებზე (`llm_usage`, `data_deletion_requests`, `webhook_inbox`,
-- `admin_audit_log`) პოლისი განზრახ არ არის: წვდომა მხოლოდ service_role-ით.
--
-- ახალი ცხრილი / პოლისი → ეს ტესტი წითელია, სანამ აქ ცხადად არ დაემატება — ეს განზრახ არის.
-- მონაცემს არ ქმნის.
begin;

create extension if not exists pgtap with schema extensions;

select plan(24);

-- (1) ცხრილების ინვენტარი
select tables_are(
  'public',
  array[
    'admin_audit_log', 'bot_conversations', 'bot_customers', 'data_deletion_requests',
    'llm_usage', 'orders', 'products', 'shops', 'subscriptions', 'upgrade_requests',
    'webhook_inbox'
  ],
  'public სქემაში ზუსტად მოსალოდნელი 11 ცხრილია'
);

-- (2) RLS ყველა ცხრილზე
select is_empty(
  $$ select c.relname from pg_class c
     join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity $$,
  'public-ის ყველა ცხრილზე RLS ჩართულია'
);

-- (3) view / materialized view არ არის
select is_empty(
  $$ select c.relname from pg_class c
     join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('v', 'm') $$,
  'public-ში view / materialized view არ არის (view RLS-ს გვერდს უვლის)'
);

-- (4) პოლისები თითო ცხრილზე
select policies_are(
  'public', 'shops',
  array['shops_select_own', 'shops_insert_own', 'shops_update_own', 'shops_delete_own'],
  'shops: 4 პოლისი'
);
select policies_are(
  'public', 'products',
  array['products_select_own', 'products_insert_own', 'products_update_own', 'products_delete_own'],
  'products: 4 პოლისი'
);
select policies_are(
  'public', 'orders',
  array['orders_select_own', 'orders_update_own', 'orders_delete_own'],
  'orders: 3 პოლისი (INSERT პოლისი არ არის — შეკვეთას backend ქმნის)'
);
select policies_are(
  'public', 'bot_customers',
  array['bot_customers_owner_read'],
  'bot_customers: მხოლოდ owner-ის წაკითხვა'
);
select policies_are(
  'public', 'bot_conversations',
  array['bot_conversations_owner_read'],
  'bot_conversations: მხოლოდ owner-ის წაკითხვა'
);
select policies_are(
  'public', 'upgrade_requests',
  array['ur_owner_select'],
  'upgrade_requests: მხოლოდ SELECT (0024-მა ur_owner_insert წაშალა)'
);
select policies_are(
  'public', 'subscriptions',
  array['subscriptions_owner_read'],
  'subscriptions: მხოლოდ owner-ის წაკითხვა'
);

-- (5) backend-only ცხრილები: პოლისი არ არის
select is_empty(
  $$ select policyname from pg_policies where schemaname = 'public' and tablename = 'llm_usage' $$,
  'llm_usage: პოლისი არ არის (backend-only)'
);
select is_empty(
  $$ select policyname from pg_policies where schemaname = 'public' and tablename = 'data_deletion_requests' $$,
  'data_deletion_requests: პოლისი არ არის (backend-only)'
);
select is_empty(
  $$ select policyname from pg_policies where schemaname = 'public' and tablename = 'webhook_inbox' $$,
  'webhook_inbox: პოლისი არ არის (backend-only)'
);
select is_empty(
  $$ select policyname from pg_policies where schemaname = 'public' and tablename = 'admin_audit_log' $$,
  'admin_audit_log: პოლისი არ არის (backend-only)'
);

-- (6) SELECT პოლისების ბრძანება და role
select policy_cmd_is('public', 'shops', 'shops_select_own', 'select', 'shops_select_own არის SELECT');
select policy_cmd_is('public', 'products', 'products_select_own', 'select', 'products_select_own არის SELECT');
select policy_cmd_is('public', 'orders', 'orders_select_own', 'select', 'orders_select_own არის SELECT');
select policy_cmd_is('public', 'bot_customers', 'bot_customers_owner_read', 'select', 'bot_customers_owner_read არის SELECT');
select policy_cmd_is('public', 'bot_conversations', 'bot_conversations_owner_read', 'select', 'bot_conversations_owner_read არის SELECT');
select policy_cmd_is('public', 'upgrade_requests', 'ur_owner_select', 'select', 'ur_owner_select არის SELECT');
select policy_cmd_is('public', 'subscriptions', 'subscriptions_owner_read', 'select', 'subscriptions_owner_read არის SELECT');
select policy_roles_are(
  'public', 'subscriptions', 'subscriptions_owner_read', array['authenticated'],
  'subscriptions_owner_read მხოლოდ authenticated-ზეა'
);

-- (7) orders_delete_own (0018): წაშლა მხოლოდ done / cancelled შეკვეთაზე
select ok(
  (select pg_get_expr(polqual, polrelid) from pg_policy
    where polrelid = 'public.orders'::regclass and polname = 'orders_delete_own') ~ 'done',
  'orders_delete_own-ის პირობა შეიცავს done-ს'
);
select ok(
  (select pg_get_expr(polqual, polrelid) from pg_policy
    where polrelid = 'public.orders'::regclass and polname = 'orders_delete_own') ~ 'cancelled',
  'orders_delete_own-ის პირობა შეიცავს cancelled-ს'
);

select * from finish();

rollback;
