-- ============================================================
-- 0005: პაკეტის განახლების მოთხოვნები (manual upgrade)
-- გამყიდველი ითხოვს პაკეტს → ადმინი ხელით ადასტურებს (გადახდის შემდეგ).
-- გაუშვი Supabase → SQL Editor-ში.
-- ============================================================

create table if not exists public.upgrade_requests (
  id             uuid primary key default gen_random_uuid(),
  shop_id        uuid not null references public.shops(id) on delete cascade,
  requested_tier text not null,
  status         text not null default 'pending',   -- pending / approved / rejected
  created_at     timestamptz not null default now(),
  resolved_at    timestamptz
);

create index if not exists upgrade_requests_status_idx
  on public.upgrade_requests (status, created_at desc);

alter table public.upgrade_requests enable row level security;

-- გამყიდველი: ქმნის მოთხოვნას საკუთარი მაღაზიისთვის
drop policy if exists "ur_owner_insert" on public.upgrade_requests;
create policy "ur_owner_insert" on public.upgrade_requests
  for insert with check (
    exists (select 1 from public.shops s
            where s.id = upgrade_requests.shop_id and s.owner_id = auth.uid())
  );

-- გამყიდველი: ხედავს საკუთარი მაღაზიის მოთხოვნებს (სტატუსის სანახავად)
drop policy if exists "ur_owner_select" on public.upgrade_requests;
create policy "ur_owner_select" on public.upgrade_requests
  for select using (
    exists (select 1 from public.shops s
            where s.id = upgrade_requests.shop_id and s.owner_id = auth.uid())
  );

-- დადასტურება/უარყოფა service_role-ით ხდება (admin), RLS-ს გვერდს უვლის.
