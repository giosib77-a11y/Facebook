-- pgTAP: RPC ფუნქციების ინვენტარი, EXECUTE grant-ები, SECURITY DEFINER (S24-2, A-042 / N-08).
--
-- რას იცავს: `public`-ის ფუნქციები ზუსტად მოსალოდნელი სიაა; არცერთ არა-trigger ფუნქციაზე
-- `anon`-ს და `authenticated`-ს EXECUTE არ აქვს (RPC-ებს მხოლოდ backend service_role-ით იძახებს);
-- SECURITY DEFINER-ები მხოლოდ ორია და ორივეს search_path ფიქსირებული აქვს; service_role-ს
-- ყველა RPC-ზე EXECUTE აქვს.
-- აფიქსირებს მიგრაციებს: 0001 (set_updated_at — trigger-ის განზრახ გამონაკლისი), 0004
-- (track_bot_customer), 0009 / 0013 (stock), 0021 (change_order_status), 0030 (purge),
-- 0032 (create_shop_limited),
-- 0034 (expire_subscriptions), 0035 (llm_tokens_used — S24-11 შლის), 0037 (claim_webhook_events,
-- purge_webhook_inbox), 0038 (llm_usage_by_model), 0039 (admin_*), 0040 (search_products).
--
-- ახალი ფუნქცია → ეს ტესტი წითელია, სანამ აქ ცხადად არ დაემატება — ეს განზრახ არის.
-- მონაცემს არ ქმნის.
begin;

create extension if not exists pgtap with schema extensions;

select plan(16);

-- (1) ფუნქციების ინვენტარი
select functions_are(
  'public',
  array[
    'admin_growth', 'admin_overview_stats', 'admin_shop_counts', 'apply_stock_delta',
    'change_order_status', 'claim_webhook_events', 'create_shop_limited', 'decrement_stock',
    'expire_subscriptions', 'llm_tokens_used', 'llm_usage_by_model',
    'purge_expired_bot_conversations', 'purge_webhook_inbox', 'search_products',
    'set_updated_at', 'track_bot_customer'
  ],
  'public სქემაში ზუსტად მოსალოდნელი 16 ფუნქციაა'
);

-- (2) anon / authenticated ვერცერთ არა-trigger ფუნქციას ვერ იძახებს
select is_empty(
  $$ select p.oid::regprocedure::text from pg_proc p
     where p.pronamespace = 'public'::regnamespace
       and p.prorettype <> 'trigger'::regtype
       and (has_function_privilege('anon', p.oid, 'EXECUTE')
            or has_function_privilege('authenticated', p.oid, 'EXECUTE')) $$,
  'არცერთ public ფუნქციაზე (trigger-ის გარდა) anon-ს / authenticated-ს EXECUTE არ აქვს'
);

-- (3) SECURITY DEFINER-ების ზუსტი სია
select results_eq(
  $$ select proname::text collate "default" from pg_proc
     where pronamespace = 'public'::regnamespace and prosecdef order by 1 $$,
  $$ values ('create_shop_limited'), ('track_bot_customer') $$,
  'SECURITY DEFINER მხოლოდ create_shop_limited და track_bot_customer'
);

-- (4) ყველა DEFINER-ს search_path ფიქსირებული აქვს
select is_empty(
  $$ select proname::text from pg_proc
     where pronamespace = 'public'::regnamespace and prosecdef
       and not coalesce(proconfig::text, '') like '%search_path=%' $$,
  'ყველა SECURITY DEFINER ფუნქციას search_path ფიქსირებული აქვს'
);

-- (5) service_role-ს EXECUTE აქვს
select ok(has_function_privilege('service_role', 'public.track_bot_customer(uuid,text)', 'EXECUTE'),
  'service_role: track_bot_customer');
select ok(has_function_privilege('service_role', 'public.decrement_stock(uuid,jsonb)', 'EXECUTE'),
  'service_role: decrement_stock');
select ok(has_function_privilege('service_role', 'public.apply_stock_delta(uuid,jsonb,integer)', 'EXECUTE'),
  'service_role: apply_stock_delta');
select ok(has_function_privilege('service_role', 'public.change_order_status(uuid,uuid,text,text)', 'EXECUTE'),
  'service_role: change_order_status');
select ok(has_function_privilege('service_role', 'public.create_shop_limited(uuid,text,text,text,text,integer)', 'EXECUTE'),
  'service_role: create_shop_limited');
select ok(has_function_privilege('service_role', 'public.claim_webhook_events(integer,integer,integer)', 'EXECUTE'),
  'service_role: claim_webhook_events');
select ok(has_function_privilege('service_role', 'public.llm_usage_by_model(uuid,uuid,timestamp with time zone)', 'EXECUTE'),
  'service_role: llm_usage_by_model');
select ok(has_function_privilege('service_role', 'public.admin_overview_stats()', 'EXECUTE'),
  'service_role: admin_overview_stats');
select ok(has_function_privilege('service_role', 'public.admin_growth(integer)', 'EXECUTE'),
  'service_role: admin_growth');
select ok(has_function_privilege('service_role', 'public.admin_shop_counts()', 'EXECUTE'),
  'service_role: admin_shop_counts');
select ok(has_function_privilege('service_role', 'public.search_products(uuid,text[],text,integer)', 'EXECUTE'),
  'service_role: search_products');
select ok(has_function_privilege('service_role', 'public.llm_tokens_used(uuid,timestamp with time zone)', 'EXECUTE'),
  'service_role: llm_tokens_used (S24-11 შლის)');

select * from finish();

rollback;
