-- ============================================================================
-- ნაბიჯი 1: ცხრილები shops + products და RLS პოლისიები
-- Multi-tenant SaaS — ქართული მაღაზიების AI ბოტი (Facebook Messenger)
--
-- გაშვება: Supabase Dashboard -> SQL Editor -> ჩასვი ეს ფაილი -> RUN
-- იდემპოტენტურია: ხელახლა გაშვება უსაფრთხოა (IF NOT EXISTS / DROP POLICY IF EXISTS).
-- ============================================================================

-- ---- გაფართოებები ----------------------------------------------------------
create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ---- helper: updated_at-ის ავტომატური განახლება -----------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ============================================================================
-- ცხრილი: shops (მაღაზიები / tenant-ები)
--   თითო მწკრივი = ერთი გამყიდველის მაღაზია. owner_id = auth.users.id
-- ============================================================================
create table if not exists public.shops (
    id                 uuid primary key default gen_random_uuid(),
    owner_id           uuid not null references auth.users (id) on delete cascade,
    name               text not null,
    description        text,
    currency           text not null default 'GEL',
    -- Facebook გვერდის დაკავშირება (ნაბიჯ 2+-ში შეივსება)
    facebook_page_id   text unique,
    facebook_page_token text,        -- TODO: production-ში დაშიფრული შენახვა
    bot_enabled        boolean not null default false,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create index if not exists shops_owner_id_idx on public.shops (owner_id);

drop trigger if exists shops_set_updated_at on public.shops;
create trigger shops_set_updated_at
    before update on public.shops
    for each row execute function public.set_updated_at();

-- ============================================================================
-- ცხრილი: products (მარაგი)
--   თითო მწკრივი = ერთი პროდუქტი, ეკუთვნის ერთ მაღაზიას.
-- ============================================================================
create table if not exists public.products (
    id           uuid primary key default gen_random_uuid(),
    shop_id      uuid not null references public.shops (id) on delete cascade,
    name         text not null,
    description  text,
    sku          text,
    price        numeric(12, 2) not null default 0 check (price >= 0),
    quantity     integer not null default 0 check (quantity >= 0),
    image_url    text,
    is_active    boolean not null default true,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists products_shop_id_idx on public.products (shop_id);
create index if not exists products_active_idx on public.products (shop_id, is_active);
-- sku უნიკალურია მაღაზიის ფარგლებში (sub-query-ის გარეშე, partial-ად null-ებზე)
create unique index if not exists products_shop_sku_uniq
    on public.products (shop_id, sku) where sku is not null;

drop trigger if exists products_set_updated_at on public.products;
create trigger products_set_updated_at
    before update on public.products
    for each row execute function public.set_updated_at();

-- ============================================================================
-- Row Level Security (RLS)
--   მთავარი იდეა: გამყიდველი ხედავს/რედაქტირებს მხოლოდ თავის მაღაზიებსა და
--   იმ პროდუქტებს, რომლებიც მის მაღაზიებს ეკუთვნის.
--   ბოტი (backend) იყენებს service_role key-ს, რომელიც RLS-ს გვერდს უვლის.
-- ============================================================================

alter table public.shops    enable row level security;
alter table public.products enable row level security;

-- ---- shops პოლისიები --------------------------------------------------------
drop policy if exists "shops_select_own" on public.shops;
create policy "shops_select_own"
    on public.shops for select
    using (auth.uid() = owner_id);

drop policy if exists "shops_insert_own" on public.shops;
create policy "shops_insert_own"
    on public.shops for insert
    with check (auth.uid() = owner_id);

drop policy if exists "shops_update_own" on public.shops;
create policy "shops_update_own"
    on public.shops for update
    using (auth.uid() = owner_id)
    with check (auth.uid() = owner_id);

drop policy if exists "shops_delete_own" on public.shops;
create policy "shops_delete_own"
    on public.shops for delete
    using (auth.uid() = owner_id);

-- ---- products პოლისიები -----------------------------------------------------
-- პროდუქტი ხილულია/რედაქტირებადია, თუ მისი shop_id ეკუთვნის მიმდინარე user-ს.
drop policy if exists "products_select_own" on public.products;
create policy "products_select_own"
    on public.products for select
    using (
        exists (
            select 1 from public.shops s
            where s.id = products.shop_id and s.owner_id = auth.uid()
        )
    );

drop policy if exists "products_insert_own" on public.products;
create policy "products_insert_own"
    on public.products for insert
    with check (
        exists (
            select 1 from public.shops s
            where s.id = products.shop_id and s.owner_id = auth.uid()
        )
    );

drop policy if exists "products_update_own" on public.products;
create policy "products_update_own"
    on public.products for update
    using (
        exists (
            select 1 from public.shops s
            where s.id = products.shop_id and s.owner_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.shops s
            where s.id = products.shop_id and s.owner_id = auth.uid()
        )
    );

drop policy if exists "products_delete_own" on public.products;
create policy "products_delete_own"
    on public.products for delete
    using (
        exists (
            select 1 from public.shops s
            where s.id = products.shop_id and s.owner_id = auth.uid()
        )
    );

-- ============================================================================
-- დასასრული. შემოწმება: Table Editor-ში უნდა გამოჩნდეს shops და products,
-- ორივეზე RLS = enabled, თითოზე 4 პოლისი.
-- ============================================================================
