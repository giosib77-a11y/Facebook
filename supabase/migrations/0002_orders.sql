-- ============================================================================
-- ნაბიჯი 7: ცხ რილი orders (შეკვეთები) + RLS
-- კლიენტი ავსებს web-ფორმას → იქმნება შეკვეთა; გამყიდველი ხედავს თავის შეკვეთებს.
--
-- გაშვება: Supabase Dashboard -> SQL Editor -> ჩასვი -> RUN
-- იდემპოტენტურია (IF NOT EXISTS / DROP POLICY IF EXISTS).
-- ============================================================================

create table if not exists public.orders (
    id                uuid primary key default gen_random_uuid(),
    shop_id           uuid not null references public.shops (id) on delete cascade,
    customer_name     text not null,
    customer_phone    text,
    customer_address  text,
    note              text,
    -- items: [{product_id, name, price, quantity}]
    items             jsonb not null default '[]'::jsonb,
    total             numeric(12, 2) not null default 0 check (total >= 0),
    -- new | processing | done | cancelled
    status            text not null default 'new',
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index if not exists orders_shop_id_idx on public.orders (shop_id);
create index if not exists orders_status_idx on public.orders (shop_id, status);
create index if not exists orders_created_idx on public.orders (shop_id, created_at desc);

drop trigger if exists orders_set_updated_at on public.orders;
create trigger orders_set_updated_at
    before update on public.orders
    for each row execute function public.set_updated_at();

-- ============================================================================
-- RLS: გამყიდველი ხედავს/ცვლის მხ ოლოდ თავისი მაღაზიის შეკვეთებს.
-- INSERT ხდება backend-ის service_role-ით (კლიენტი ავტორიზებული არ არის),
-- ამიტომ public insert პოლისი არ გვჭირდება — service_role RLS-ს გვერდს უვლის.
-- ============================================================================
alter table public.orders enable row level security;

drop policy if exists "orders_select_own" on public.orders;
create policy "orders_select_own"
    on public.orders for select
    using (
        exists (
            select 1 from public.shops s
            where s.id = orders.shop_id and s.owner_id = auth.uid()
        )
    );

drop policy if exists "orders_update_own" on public.orders;
create policy "orders_update_own"
    on public.orders for update
    using (
        exists (
            select 1 from public.shops s
            where s.id = orders.shop_id and s.owner_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.shops s
            where s.id = orders.shop_id and s.owner_id = auth.uid()
        )
    );

drop policy if exists "orders_delete_own" on public.orders;
create policy "orders_delete_own"
    on public.orders for delete
    using (
        exists (
            select 1 from public.shops s
            where s.id = orders.shop_id and s.owner_id = auth.uid()
        )
    );

-- დასასრული. Table Editor-ში უნდა გამოჩნდეს orders, RLS=enabled, 3 პოლისი.
