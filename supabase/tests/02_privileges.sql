-- pgTAP: ცხრილის / სვეტის / sequence-ის grant-ები (S24-3, A-042 / N-08).
--
-- რას იცავს: backend-only ცხრილებზე `anon`-ს და `authenticated`-ს privilege არ აქვს;
-- `shops` / `products`-ზე `authenticated` მხოლოდ ზუსტად მოსალოდნელ სვეტებს ცვლის (ახალი სვეტი
-- ავტომატურად არა-ჩაწერადია — ტესტი წითლდება, სანამ აქ ცხადად არ დაემატება); `orders`
-- სტატუსს მხოლოდ RPC (change_order_status, service_role) ცვლის; `admin_audit_log` append-only.
-- აფიქსირებს მიგრაციებს: 0015, 0017, 0018, 0022 (shops / products / orders სვეტების grant-ები),
-- 0024 (upgrade_requests), 0025 (llm_usage), 0029 (data_deletion_requests), 0034 (subscriptions),
-- 0037 (webhook_inbox), 0041 (admin_audit_log + sequence).
--
-- განზრახ არ მოწმდება (ცნობილი ნაკლი, Backlog „Stage 24"; PROJECT.md Decision Log
-- 2026-11-06): `bot_conversations` / `bot_customers`-ის ჩაწერის privilege-ები, `products` DELETE
-- (`anon`), `orders` INSERT — Supabase-ის default grant-ებით ისინი აქვთ, დაცვა მხოლოდ RLS-ია;
-- ქცევას ამოწმებს 04_tenant_isolation.sql.
-- მონაცემს არ ქმნის.
begin;

create extension if not exists pgtap with schema extensions;

select plan(40);

-- (1) backend-only ცხრილები: anon / authenticated — privilege არცერთი
select table_privs_are('public', 'llm_usage', 'anon', array[]::text[],
  'llm_usage: anon-ს privilege არ აქვს');
select table_privs_are('public', 'llm_usage', 'authenticated', array[]::text[],
  'llm_usage: authenticated-ს privilege არ აქვს');
select table_privs_are('public', 'data_deletion_requests', 'anon', array[]::text[],
  'data_deletion_requests: anon-ს privilege არ აქვს');
select table_privs_are('public', 'data_deletion_requests', 'authenticated', array[]::text[],
  'data_deletion_requests: authenticated-ს privilege არ აქვს');
select table_privs_are('public', 'webhook_inbox', 'anon', array[]::text[],
  'webhook_inbox: anon-ს privilege არ აქვს');
select table_privs_are('public', 'webhook_inbox', 'authenticated', array[]::text[],
  'webhook_inbox: authenticated-ს privilege არ აქვს');
select table_privs_are('public', 'admin_audit_log', 'anon', array[]::text[],
  'admin_audit_log: anon-ს privilege არ აქვს');
select table_privs_are('public', 'admin_audit_log', 'authenticated', array[]::text[],
  'admin_audit_log: authenticated-ს privilege არ აქვს');

-- (2) subscriptions: anon არაფერი, authenticated მხოლოდ SELECT
select table_privs_are('public', 'subscriptions', 'anon', array[]::text[],
  'subscriptions: anon-ს privilege არ აქვს');
select table_privs_are('public', 'subscriptions', 'authenticated', array['SELECT'],
  'subscriptions: authenticated-ს მხოლოდ SELECT აქვს');

-- (3) service_role
select table_privs_are('public', 'admin_audit_log', 'service_role', array['INSERT', 'SELECT'],
  'admin_audit_log: service_role-ს მხოლოდ INSERT და SELECT (append-only)');
select ok(
  has_table_privilege('service_role', 'public.webhook_inbox', 'SELECT')
  and has_table_privilege('service_role', 'public.webhook_inbox', 'INSERT')
  and has_table_privilege('service_role', 'public.webhook_inbox', 'UPDATE')
  and has_table_privilege('service_role', 'public.webhook_inbox', 'DELETE'),
  'webhook_inbox: service_role-ს SELECT / INSERT / UPDATE / DELETE აქვს'
);

-- (4) shops: ცხრილის დონეზე ჩაწერა არა; authenticated ცვლის მხოლოდ 4 სვეტს
select ok(not has_table_privilege('anon', 'public.shops', 'INSERT'), 'shops: anon INSERT არა');
select ok(not has_table_privilege('authenticated', 'public.shops', 'INSERT'),
  'shops: authenticated INSERT არა');
select ok(not has_table_privilege('anon', 'public.shops', 'UPDATE'), 'shops: anon UPDATE (ცხრილი) არა');
select ok(not has_table_privilege('authenticated', 'public.shops', 'UPDATE'),
  'shops: authenticated UPDATE (ცხრილი) არა');
select ok(not has_table_privilege('anon', 'public.shops', 'DELETE'), 'shops: anon DELETE არა');
select ok(not has_table_privilege('authenticated', 'public.shops', 'DELETE'),
  'shops: authenticated DELETE არა');
select results_eq(
  $$ select column_name::text collate "default" from information_schema.columns
     where table_schema = 'public' and table_name = 'shops'
       and has_column_privilege('authenticated', 'public.shops', column_name, 'UPDATE')
     order by 1 $$,
  $$ values ('bot_language'), ('currency'), ('description'), ('name') $$,
  'shops: authenticated-ის UPDATE-ადი სვეტები ზუსტად bot_language, currency, description, name'
);
select is_empty(
  $$ select column_name::text from information_schema.columns
     where table_schema = 'public' and table_name = 'shops'
       and has_column_privilege('anon', 'public.shops', column_name, 'UPDATE') $$,
  'shops: anon-ს UPDATE-ადი სვეტი არცერთი აქვს'
);

-- (5) products: INSERT არა; authenticated ცვლის მხოლოდ 7 სვეტს
select ok(not has_table_privilege('anon', 'public.products', 'INSERT'), 'products: anon INSERT არა');
select ok(not has_table_privilege('authenticated', 'public.products', 'INSERT'),
  'products: authenticated INSERT არა');
select results_eq(
  $$ select column_name::text collate "default" from information_schema.columns
     where table_schema = 'public' and table_name = 'products'
       and has_column_privilege('authenticated', 'public.products', column_name, 'UPDATE')
     order by 1 $$,
  $$ values ('description'), ('image_url'), ('is_active'), ('name'), ('price'), ('quantity'),
            ('sku') $$,
  'products: authenticated-ის UPDATE-ადი სვეტები ზუსტად description, image_url, is_active, name, price, quantity, sku'
);
select is_empty(
  $$ select column_name::text from information_schema.columns
     where table_schema = 'public' and table_name = 'products'
       and has_column_privilege('anon', 'public.products', column_name, 'UPDATE') $$,
  'products: anon-ს UPDATE-ადი სვეტი არცერთი აქვს'
);

-- (6) orders: UPDATE (ცხრილი და status) არა; DELETE მხოლოდ authenticated-ს (პოლისი ზღუდავს)
select ok(not has_table_privilege('anon', 'public.orders', 'UPDATE'), 'orders: anon UPDATE (ცხრილი) არა');
select ok(not has_table_privilege('authenticated', 'public.orders', 'UPDATE'),
  'orders: authenticated UPDATE (ცხრილი) არა');
select ok(not has_column_privilege('anon', 'public.orders', 'status', 'UPDATE'),
  'orders: anon status UPDATE არა');
select ok(not has_column_privilege('authenticated', 'public.orders', 'status', 'UPDATE'),
  'orders: authenticated status UPDATE არა');
select ok(not has_table_privilege('anon', 'public.orders', 'DELETE'), 'orders: anon DELETE არა');
select ok(has_table_privilege('authenticated', 'public.orders', 'DELETE'),
  'orders: authenticated DELETE აქვს (პოლისი ზღუდავს done / cancelled-ზე)');
select ok(has_table_privilege('authenticated', 'public.orders', 'SELECT'),
  'orders: authenticated SELECT აქვს');

-- (7) upgrade_requests: ჩაწერა არა, authenticated კითხულობს
select ok(not has_table_privilege('anon', 'public.upgrade_requests', 'INSERT'),
  'upgrade_requests: anon INSERT არა');
select ok(not has_table_privilege('authenticated', 'public.upgrade_requests', 'INSERT'),
  'upgrade_requests: authenticated INSERT არა');
select ok(not has_table_privilege('anon', 'public.upgrade_requests', 'UPDATE'),
  'upgrade_requests: anon UPDATE არა');
select ok(not has_table_privilege('authenticated', 'public.upgrade_requests', 'UPDATE'),
  'upgrade_requests: authenticated UPDATE არა');
select ok(not has_table_privilege('anon', 'public.upgrade_requests', 'DELETE'),
  'upgrade_requests: anon DELETE არა');
select ok(not has_table_privilege('authenticated', 'public.upgrade_requests', 'DELETE'),
  'upgrade_requests: authenticated DELETE არა');
select ok(has_table_privilege('authenticated', 'public.upgrade_requests', 'SELECT'),
  'upgrade_requests: authenticated SELECT აქვს');

-- (8) sequence
select ok(not has_sequence_privilege('anon', 'public.admin_audit_log_id_seq', 'USAGE'),
  'admin_audit_log_id_seq: anon USAGE არა');
select ok(not has_sequence_privilege('authenticated', 'public.admin_audit_log_id_seq', 'USAGE'),
  'admin_audit_log_id_seq: authenticated USAGE არა');

select * from finish();

rollback;
