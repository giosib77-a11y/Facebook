-- 0012: პროდუქტის ფოტო (image_url)
-- თითო პროდუქტს შეიძლება ჰქონდეს სურათი (Supabase Storage-ის public URL).
-- ბოტი ამ ფოტოებს იყენებს კლიენტის შემოსული ფოტოს ვიზუალურად შესადარებლად.

alter table public.products
  add column if not exists image_url text;
