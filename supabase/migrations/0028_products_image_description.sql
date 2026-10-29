-- ============================================================================
-- 0028: products.image_description — პროდუქტის ფოტოს მოკლე აღწერა (S18-1, Stage 18)
--
-- დანიშნულება
-- პროდუქტის ფოტოს მოკლე ტექსტური აღწერა (≤500 სიმბოლო, ორი ხაზი: `EN:` + `KA:`). ბოტი მას ერთხელ ქმნის,
-- როცა ფოტო დგება ან იცვლება (პროდუქტის შექმნა / რედაქტირება), ან backfill სკრიპტით (არსებული ფოტოებისთვის).
-- გამოიყენება მხოლოდ ბოტის პროდუქტის ძებნასა და კლიენტის ფოტოზე საცნობარო კანდიდატების არჩევაში;
-- prompt-ის SHOP block-ში არ ჩანს.
-- nullable: null = აღწერა არ არის (ძველი ფოტო, აღწერის გენერაცია ჩავარდა, ფოტო არ არის) →
-- ბოტი ამ პროდუქტს ტექსტური რანჟირებით ირჩევს, როგორც აქამდე.
--
-- უსაფრთხოება
-- ჩაწერა მხოლოდ backend-იდან — service client, მფლობელობის შემოწმების შემდეგ, პირობითად `image_url`-ზე
-- (თუ ფოტო აღწერის დროს შეიცვალა, ძველი აღწერა ახალს არ გადაეწერება). 0015-ით `authenticated`-ს `products`-ზე
-- ცხრილის დონის INSERT/UPDATE არ აქვს, ხოლო სვეტის დონის UPDATE მხოლოდ
-- `name, description, sku, price, quantity, image_url, is_active`-ზეა (მოგვიანებით `products`-ის უფლებები
-- არცერთ მიგრაციაში არ შეცვლილა) → ახალი სვეტი გამყიდველისთვის PostgREST-ით ჩაუწერადია.
-- ამიტომ ამ ფაილში არც უფლების მიცემაა, არც ჩამორთმევა, არც პოლისი.
-- SELECT — საკუთარი პროდუქტები RLS-ით (0001), ექსპორტშიც ჩანს.
-- აღწერა იშლება პროდუქტთან ერთად (products-ის მწკრივთან ერთად).
--
-- ⚠️ გაუშვი Stage 18-ის backend deploy-მდე (რეკომენდებული). backend სვეტის გარეშეც მუშაობს
--    (ფოტოს აღწერა გამორთულია, ერთჯერადი WARNING ლოგში); ძველ backend-ს ახალი სვეტი არ აწუხებს.
--    backfill სკრიპტი (`backend/scripts/backfill_image_descriptions.py`) — მხოლოდ ამის შემდეგ.
--
-- იდემპოტენტურია (add column if not exists / comment on ხელახლა გაშვებაზე უსაფრთხოა).
-- გაშვება: მფლობელი ხელით — Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

begin;

alter table public.products
  add column if not exists image_description text;

comment on column public.products.image_description is
  'Stage 18: short text description of the product photo (<=500 chars); written only by the backend';

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select data_type, is_nullable
--   from information_schema.columns
--   where table_schema = 'public' and table_name = 'products' and column_name = 'image_description';
--   -- სწორი შედეგი: text, YES
--
--   select
--     has_column_privilege('authenticated','public.products','image_description','UPDATE') as desc_upd,
--     has_table_privilege('authenticated','public.products','UPDATE')                      as tbl_upd,
--     has_table_privilege('authenticated','public.products','INSERT')                      as tbl_ins,
--     has_column_privilege('authenticated','public.products','image_description','SELECT') as desc_sel,
--     has_column_privilege('service_role','public.products','image_description','UPDATE')  as svc_upd;
--   -- სწორი შედეგი: f, f, f, t, t
--
-- ROLLBACK (მხოლოდ თუ საჭიროა; წაშლის შენახულ აღწერებს — ბოტი ტექსტურ რანჟირებაზე დაბრუნდება):
--   alter table public.products drop column if exists image_description;
-- ============================================================================
