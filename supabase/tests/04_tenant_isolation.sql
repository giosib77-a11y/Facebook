-- pgTAP: tenant isolation და anon-ის ქცევა (S24-4, A-042 / N-08).
--
-- რას იცავს: `authenticated` მომხმარებელი A ხედავს მხოლოდ საკუთარ მწკრივებს (shops, products, orders,
-- bot_conversations, bot_customers, upgrade_requests, subscriptions), backend-only ცხრილებიდან (llm_usage,
-- webhook_inbox, data_deletion_requests, admin_audit_log) არაფერს, და ვერ ცვლის B-ს მონაცემს ან
-- პრივილეგირებულ სვეტებს; `anon` ვერაფერს კითხულობს და ვერაფერს ცვლის.
-- ტესტი ამოწმებს ცვლილების არარსებობას (postgres-ით, `reset role`-ის შემდეგ), არა შეცდომის კოდს:
-- RLS-ით დაბლოკილი delete/update შეიძლება იყოს 42501 ან 0 მწკრივი.
-- აფიქსირებს მიგრაციებს: 0001, 0002, 0004, 0005, 0008, 0015, 0018, 0019, 0022, 0024, 0025, 0029, 0034, 0037, 0041.
-- ყველაფერი ერთ ტრანზაქციაშია (rollback), helper-ები `tests` სქემაში ქრება.
begin;

create extension if not exists pgtap with schema extensions;

select plan(40);

-- ---------------------------------------------------------------------------
-- setup (postgres): მომხმარებლები A, B და თითოს მონაცემები
-- ---------------------------------------------------------------------------
insert into auth.users (id, email) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'a@example.test'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'b@example.test');

insert into public.shops (id, owner_id, name) values
  ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'A shop'),
  ('b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'B shop');

insert into public.products (id, shop_id, name) values
  ('a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'A product'),
  ('b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2', 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', 'B product');

insert into public.orders (id, shop_id, customer_name, status) values
  ('a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'A new', 'new'),
  ('a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4', 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'A done', 'done'),
  ('b3b3b3b3-b3b3-b3b3-b3b3-b3b3b3b3b3b3', 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', 'B new', 'new'),
  ('b4b4b4b4-b4b4-b4b4-b4b4-b4b4b4b4b4b4', 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', 'B done', 'done');

insert into public.bot_conversations (shop_id, psid) values
  ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', '111'),
  ('b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', '222');

insert into public.bot_customers (shop_id, psid, ym) values
  ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', '111', '2026-11'),
  ('b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', '222', '2026-11');

insert into public.upgrade_requests (shop_id, requested_tier, status) values
  ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'basic', 'pending'),
  ('b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', 'basic', 'pending');

insert into public.subscriptions (owner_id, tier) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'basic'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'basic');

insert into public.llm_usage (shop_id, provider, model) values
  ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'claude', 'test-model');
insert into public.webhook_inbox (page_id, mid, object) values ('123', 'm1', 'page');
insert into public.data_deletion_requests (code) values ('code1');
insert into public.admin_audit_log (admin_id, action) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'shop.update');

-- ---------------------------------------------------------------------------
-- helper-ები (ტრანზაქციაში; rollback შლის)
-- ---------------------------------------------------------------------------
create schema tests;
grant usage on schema tests to anon, authenticated;

-- ხილული მწკრივების რაოდენობა მიმდინარე როლით; privilege არ აქვს -> 0
create function tests.visible_rows(t regclass) returns bigint
language plpgsql security invoker as $$
declare n bigint;
begin
  execute format('select count(*) from %s', t) into n;
  return n;
exception when insufficient_privilege then
  return 0;
end;
$$;

-- SQL-ის შესრულება; წარმატება -> 'ok', შეცდომა -> sqlstate
create function tests.try_exec(sql text) returns text
language plpgsql security invoker as $$
begin
  execute sql;
  return 'ok';
exception when others then
  return sqlstate;
end;
$$;

-- 11 ცხრილის მწკრივების რაოდენობა (postgres-ით, snapshot-ისთვის)
create function tests.counts() returns table (t text, n bigint)
language sql as $$
  select 'shops'::text, count(*) from public.shops
  union all select 'products', count(*) from public.products
  union all select 'orders', count(*) from public.orders
  union all select 'bot_conversations', count(*) from public.bot_conversations
  union all select 'bot_customers', count(*) from public.bot_customers
  union all select 'upgrade_requests', count(*) from public.upgrade_requests
  union all select 'subscriptions', count(*) from public.subscriptions
  union all select 'llm_usage', count(*) from public.llm_usage
  union all select 'webhook_inbox', count(*) from public.webhook_inbox
  union all select 'data_deletion_requests', count(*) from public.data_deletion_requests
  union all select 'admin_audit_log', count(*) from public.admin_audit_log;
$$;

grant execute on function tests.visible_rows(regclass), tests.try_exec(text) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- (1) authenticated A: ხედავს მხოლოდ საკუთარს (positive control: A-ს მწკრივი ჩანს)
-- ---------------------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims',
  json_build_object('sub', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'role', 'authenticated')::text, true);
select set_config('request.jwt.claim.sub', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);

select results_eq(
  $$select id::text from public.shops order by 1$$,
  $$values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1')$$,
  'A: shops - მხოლოდ A-ს მაღაზია');
select results_eq(
  $$select id::text from public.products order by 1$$,
  $$values ('a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2')$$,
  'A: products - მხოლოდ A-ს პროდუქტი');
select results_eq(
  $$select id::text from public.orders order by 1$$,
  $$values ('a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3'), ('a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4')$$,
  'A: orders - მხოლოდ A-ს ორი შეკვეთა');
select results_eq(
  $$select shop_id::text || '/' || psid from public.bot_conversations order by 1$$,
  $$values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1/111')$$,
  'A: bot_conversations - მხოლოდ A-ს');
select results_eq(
  $$select shop_id::text || '/' || psid from public.bot_customers order by 1$$,
  $$values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1/111')$$,
  'A: bot_customers - მხოლოდ A-ს');
select results_eq(
  $$select shop_id::text from public.upgrade_requests order by 1$$,
  $$values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1')$$,
  'A: upgrade_requests - მხოლოდ A-ს');
select results_eq(
  $$select owner_id::text from public.subscriptions order by 1$$,
  $$values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')$$,
  'A: subscriptions - მხოლოდ A-ს');

-- backend-only ცხრილები: არაფერი ჩანს
select is(tests.visible_rows('public.llm_usage'), 0::bigint, 'A: llm_usage - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.webhook_inbox'), 0::bigint, 'A: webhook_inbox - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.data_deletion_requests'), 0::bigint,
  'A: data_deletion_requests - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.admin_audit_log'), 0::bigint, 'A: admin_audit_log - 0 ხილული მწკრივი');

-- ცვლილების მცდელობები (შედეგი არ მოწმდება; უცვლელობა - reset role-ის შემდეგ)
do $do$
begin
  perform tests.try_exec($q$update public.shops set name = 'hacked' where id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'$q$);
  perform tests.try_exec($q$update public.shops set owner_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' where id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'$q$);
  perform tests.try_exec($q$delete from public.products where id = 'b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2'$q$);
  perform tests.try_exec($q$delete from public.orders where id = 'b4b4b4b4-b4b4-b4b4-b4b4-b4b4b4b4b4b4'$q$);
  perform tests.try_exec($q$delete from public.bot_conversations where shop_id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'$q$);
  perform tests.try_exec($q$update public.subscriptions set tier = 'business'$q$);
  perform tests.try_exec($q$insert into public.subscriptions (owner_id, tier) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'business')$q$);
  perform tests.try_exec($q$insert into public.products (shop_id, name) values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'extra')$q$);
  perform tests.try_exec($q$insert into public.upgrade_requests (shop_id, requested_tier, status) values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', 'business', 'pending')$q$);
  perform tests.try_exec($q$update public.shops set subscription_tier = 'business' where id = 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1'$q$);
  -- საკუთარი 'new' შეკვეთა არ იშლება (0018: delete მხოლოდ done/cancelled-ზე)
  perform tests.try_exec($q$delete from public.orders where id = 'a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3'$q$);
end;
$do$;

-- positive: საკუთარი 'done' შეკვეთის delete წარმატებულია (0018)
select is(
  tests.try_exec($q$delete from public.orders where id = 'a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4'$q$),
  'ok', 'A: საკუთარი done შეკვეთის delete - ok');

reset role;

select is((select count(*) from public.orders where id = 'a4a4a4a4-a4a4-a4a4-a4a4-a4a4a4a4a4a4'), 0::bigint,
  'A: done შეკვეთა წაიშალა');
select is((select count(*) from public.orders where id = 'a3a3a3a3-a3a3-a3a3-a3a3-a3a3a3a3a3a3'), 1::bigint,
  'A: new შეკვეთა არ წაიშალა');
select is((select name from public.shops where id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'), 'B shop',
  'B: shops.name უცვლელია');
select is((select owner_id::text from public.shops where id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'),
  'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'B: shops.owner_id უცვლელია');
select is((select subscription_tier from public.shops where id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'), 'free',
  'B: shops.subscription_tier უცვლელია');
select is((select subscription_tier from public.shops where id = 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1'), 'free',
  'A: საკუთარი shops.subscription_tier ვერ შეიცვალა');
select is((select count(*) from public.products where shop_id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'), 1::bigint,
  'B: პროდუქტი არ წაიშალა');
select is((select count(*) from public.orders where shop_id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'), 2::bigint,
  'B: ორივე შეკვეთა არსებობს');
select is((select count(*) from public.bot_conversations where shop_id = 'b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1'), 1::bigint,
  'B: bot_conversations არ წაიშალა');
select results_eq(
  $$select owner_id::text, tier from public.subscriptions order by 1$$,
  $$values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'basic'), ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'basic')$$,
  'subscriptions: ორივე tier უცვლელია (basic), ახალი მწკრივი არ დამატებულა');
select is((select count(*) from public.products where shop_id = 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1'), 1::bigint,
  'A: products insert არ მოხდა');
select results_eq(
  $$select requested_tier, status from public.upgrade_requests where shop_id = 'a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1'$$,
  $$values ('basic', 'pending')$$,
  'A: upgrade_requests insert არ მოხდა');

-- ---------------------------------------------------------------------------
-- (2) anon: ვერაფერს კითხულობს და ვერაფერს ცვლის
-- ---------------------------------------------------------------------------
create table tests.snap as select * from tests.counts();

select ok((select bool_and(n > 0) and count(*) = 11 from tests.snap),
  'setup: ყველა 11 ცხრილში postgres-ით მონაცემი ჩანს (positive control)');

set local role anon;
select set_config('request.jwt.claims', '{"role": "anon"}', true);
select set_config('request.jwt.claim.sub', '', true);

select is(tests.visible_rows('public.shops'), 0::bigint, 'anon: shops - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.products'), 0::bigint, 'anon: products - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.orders'), 0::bigint, 'anon: orders - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.bot_conversations'), 0::bigint, 'anon: bot_conversations - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.bot_customers'), 0::bigint, 'anon: bot_customers - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.upgrade_requests'), 0::bigint, 'anon: upgrade_requests - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.subscriptions'), 0::bigint, 'anon: subscriptions - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.llm_usage'), 0::bigint, 'anon: llm_usage - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.webhook_inbox'), 0::bigint, 'anon: webhook_inbox - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.data_deletion_requests'), 0::bigint,
  'anon: data_deletion_requests - 0 ხილული მწკრივი');
select is(tests.visible_rows('public.admin_audit_log'), 0::bigint, 'anon: admin_audit_log - 0 ხილული მწკრივი');

do $do$
begin
  perform tests.try_exec($q$delete from public.shops$q$);
  perform tests.try_exec($q$update public.shops set name = name$q$);
  perform tests.try_exec($q$delete from public.products$q$);
  perform tests.try_exec($q$update public.products set name = name$q$);
  perform tests.try_exec($q$delete from public.orders$q$);
  perform tests.try_exec($q$update public.orders set status = status$q$);
  perform tests.try_exec($q$delete from public.bot_conversations$q$);
  perform tests.try_exec($q$update public.bot_conversations set psid = psid$q$);
  perform tests.try_exec($q$delete from public.bot_customers$q$);
  perform tests.try_exec($q$update public.bot_customers set psid = psid$q$);
  perform tests.try_exec($q$delete from public.upgrade_requests$q$);
  perform tests.try_exec($q$update public.upgrade_requests set status = status$q$);
  perform tests.try_exec($q$delete from public.subscriptions$q$);
  perform tests.try_exec($q$update public.subscriptions set tier = tier$q$);
  perform tests.try_exec($q$delete from public.llm_usage$q$);
  perform tests.try_exec($q$update public.llm_usage set model = model$q$);
  perform tests.try_exec($q$delete from public.webhook_inbox$q$);
  perform tests.try_exec($q$update public.webhook_inbox set status = status$q$);
  perform tests.try_exec($q$delete from public.data_deletion_requests$q$);
  perform tests.try_exec($q$update public.data_deletion_requests set status = status$q$);
  perform tests.try_exec($q$delete from public.admin_audit_log$q$);
  perform tests.try_exec($q$update public.admin_audit_log set action = action$q$);
  perform tests.try_exec($q$insert into public.orders (shop_id, customer_name) values ('b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1', 'x')$q$);
  perform tests.try_exec($q$insert into public.bot_conversations (shop_id, psid) values ('a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1', '999')$q$);
  perform tests.try_exec($q$insert into public.shops (owner_id, name) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'x')$q$);
end;
$do$;

reset role;

select results_eq(
  $$select t, n from tests.counts() order by t$$,
  $$select t, n from tests.snap order by t$$,
  'anon: delete/update/insert-ის შემდეგ ყველა 11 ცხრილის მწკრივების რაოდენობა უცვლელია');
select is((select count(*) from public.orders where customer_name = 'x'), 0::bigint,
  'anon: orders insert არ მოხდა');
select is((select count(*) from public.bot_conversations where psid = '999'), 0::bigint,
  'anon: bot_conversations insert არ მოხდა');
select is((select count(*) from public.shops where name = 'x'), 0::bigint,
  'anon: shops insert არ მოხდა');

select * from finish();

rollback;
