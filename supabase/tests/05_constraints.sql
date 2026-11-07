-- pgTAP: CHECK-ზღვრები (S24-12, A-042 / N-08) — ჯერ მხოლოდ shops.knowledge.
--
-- რას იცავს: `shops_knowledge_len_chk` = `char_length(knowledge) <= 50000` (0043; PDF-ის ჭერი
-- `services/pdf_extract.MAX_CHARS`). 50 000 სიმბოლო (ქართული, მრავალბაიტიანი) ჩაიწერება, 50 001 — `23514`.
-- აფიქსირებს მიგრაციებს: 0016 (ძველი 21 000), 0043 (50 000).
-- ყველაფერი ერთ ტრანზაქციაშია (rollback).
begin;

create extension if not exists pgtap with schema extensions;

select plan(3);

-- (1) constraint-ის განმარტება
select is(
  (select pg_get_constraintdef(oid) from pg_constraint
    where conrelid = 'public.shops'::regclass and conname = 'shops_knowledge_len_chk'),
  'CHECK ((char_length(knowledge) <= 50000))',
  'shops_knowledge_len_chk: char_length(knowledge) <= 50000');

-- setup (postgres): მომხმარებელი + მაღაზია
insert into auth.users (id, email) values
  ('c0c0c0c0-c0c0-c0c0-c0c0-c0c0c0c0c0c0', 'constraints@example.test');
insert into public.shops (id, owner_id, name) values
  ('c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1', 'c0c0c0c0-c0c0-c0c0-c0c0-c0c0c0c0c0c0', 'Constraints shop');

-- (2) ზუსტად 50 000 სიმბოლო გადის
select lives_ok(
  $$update public.shops set knowledge = repeat('ა', 50000)
    where id = 'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1'$$,
  'knowledge: 50 000 სიმბოლო ჩაიწერება');

-- (3) 50 001 სიმბოლო -> check_violation
select throws_ok(
  $$update public.shops set knowledge = repeat('ა', 50001)
    where id = 'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1'$$,
  '23514',
  null,
  'knowledge: 50 001 სიმბოლო -> 23514');

select * from finish();
rollback;
