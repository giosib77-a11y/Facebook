-- ============================================================================
-- 0010: ოპერატორზე გადართვა (handoff) — „ყურადღება სჭირდება" ნიშანი
--
-- როცა ბოტი ვერ პასუხობს ან კლიენტი ადამიან-ოპერატორს ითხოვს, საუბარი ინიშნება.
-- გამყიდველი პანელში ხედავს ასეთ საუბრებს და ხელით ერთვება Messenger/Instagram-ში.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

alter table public.bot_conversations
  add column if not exists needs_attention boolean not null default false,
  add column if not exists attention_at    timestamptz;

-- სწრაფი ამორჩევა: მაღაზიის „ყურადღების" საუბრები
create index if not exists bot_conversations_attention_idx
  on public.bot_conversations (shop_id)
  where needs_attention;

-- ============================================================================
-- შემოწმება: bot_conversations-ს დაემატა needs_attention (bool) + attention_at.
-- ============================================================================
