-- ============================================================
-- 0008: ბოტის საუბრის მეხსიერება
-- თითო კლიენტზე (მაღაზია + Messenger/IG user) ბოლო შეტყობინებები —
-- ბოტი კონტექსტს ინახავს და თანმიმდევრულად პასუხობს.
-- გაუშვი Supabase → SQL Editor-ში.
-- ============================================================

create table if not exists public.bot_conversations (
  shop_id    uuid not null references public.shops(id) on delete cascade,
  psid       text not null,                       -- Messenger/Instagram user id
  messages   jsonb not null default '[]'::jsonb,  -- [{role:'user'|'bot', content:'...'}]
  updated_at timestamptz not null default now(),
  primary key (shop_id, psid)
);

-- RLS: გამყიდველი ხედავს მხოლოდ საკუთარი მაღაზიის საუბრებს.
-- ჩაწერა service_role-ით ხდება (webhook), რომელიც RLS-ს გვერდს უვლის.
alter table public.bot_conversations enable row level security;

drop policy if exists "bot_conversations_owner_read" on public.bot_conversations;
create policy "bot_conversations_owner_read" on public.bot_conversations
  for select using (
    exists (select 1 from public.shops s
            where s.id = bot_conversations.shop_id and s.owner_id = auth.uid())
  );
