-- ============================================================
-- 0004: მონეტიზაცია — გამოწერის პაკეტი + კლიენტების თვლა
-- გაუშვი Supabase → SQL Editor-ში.
-- ============================================================

-- პაკეტი მაღაზიაზე (free / basic / standard / business)
alter table public.shops
  add column if not exists subscription_tier text not null default 'free';

-- ბოტის კლიენტების თვლა (უნიკალური Messenger user თვეში + დღიური abuse-cap)
create table if not exists public.bot_customers (
  shop_id    uuid not null references public.shops(id) on delete cascade,
  psid       text not null,                       -- Messenger user id
  ym         text not null,                       -- 'YYYY-MM' (თვის ბაკეტი)
  msg_count  int  not null default 0,             -- შეტყობინება ამ თვეს
  day        text,                                -- 'YYYY-MM-DD' (დღიური cap-ისთვის)
  day_count  int  not null default 0,             -- შეტყობინება ამ დღეს
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (shop_id, psid, ym)
);

create index if not exists bot_customers_shop_ym_idx
  on public.bot_customers (shop_id, ym);

-- RLS: გამყიდველი ხედავს მხოლოდ საკუთარი მაღაზიის თვლას (usage-ის საჩვენებლად).
-- ჩაწერა service_role-ით ხდება (webhook), რომელიც RLS-ს გვერდს უვლის.
alter table public.bot_customers enable row level security;

drop policy if exists "bot_customers_owner_read" on public.bot_customers;
create policy "bot_customers_owner_read" on public.bot_customers
  for select using (
    exists (select 1 from public.shops s
            where s.id = bot_customers.shop_id and s.owner_id = auth.uid())
  );

-- ატომური ტრეკინგი: ამატებს/ანახლებს კლიენტს და აბრუნებს
-- (თვის უნიკალურ კლიენტთა რაოდენობას, ამ კლიენტის დღიურ count-ს).
create or replace function public.track_bot_customer(p_shop uuid, p_psid text)
returns table (monthly_unique int, day_count int)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ym  text := to_char(now(), 'YYYY-MM');
  v_day text := to_char(now(), 'YYYY-MM-DD');
begin
  insert into public.bot_customers (shop_id, psid, ym, msg_count, day, day_count)
    values (p_shop, p_psid, v_ym, 1, v_day, 1)
  on conflict (shop_id, psid, ym) do update
    set msg_count  = public.bot_customers.msg_count + 1,
        day_count  = case when public.bot_customers.day = v_day
                          then public.bot_customers.day_count + 1 else 1 end,
        day        = v_day,
        updated_at = now();

  return query
    select
      (select count(*)::int from public.bot_customers
         where shop_id = p_shop and ym = v_ym),
      (select b.day_count from public.bot_customers b
         where b.shop_id = p_shop and b.psid = p_psid and b.ym = v_ym);
end;
$$;
