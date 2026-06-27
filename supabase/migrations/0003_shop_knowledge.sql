-- ============================================================================
-- ნაბიჯი 9: shops-ს დაემატება ცოდნის ველები (PDF-დან ამოღებული ტექსტი).
-- გამყიდველი ტვირთავს PDF-ს → ტექსტი ინახ ება → ბოტი იყენებს პასუხ ებში
-- (მიწოდება, გარანტია, FAQ, დეტალური ინფო).
--
-- გაშვება: Supabase Dashboard -> SQL Editor -> ჩასვი -> RUN
-- იდემპოტენტურია (IF NOT EXISTS).
-- ============================================================================

alter table public.shops
    add column if not exists knowledge text;

alter table public.shops
    add column if not exists knowledge_filename text;

-- არსებული RLS პოლისები საკმარისია — ეს ველები shops-ის ნაწილია.
