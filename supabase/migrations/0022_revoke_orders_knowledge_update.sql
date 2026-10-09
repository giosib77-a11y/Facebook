-- ============================================================================
-- 0022: orders — UPDATE მოხსნილია authenticated-დან; shops.knowledge* — UPDATE მოხსნილია (S11-5)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- 1) orders: 0018-მა authenticated-ს დაუტოვა UPDATE(status). backend სტატუსს მხოლოდ
--    RPC change_order_status-ით ცვლის (0021, service_role), ამიტომ ეს grant ზედმეტია,
--    და PostgREST-ით პირდაპირი PATCH {"status": ...} RPC-ს გვერდს უვლის: მარაგი
--    აღარ დაკლდება/დაბრუნდება (მარაგის გაბერვა/გაყალბება).
-- 2) shops.knowledge / knowledge_filename: 0015-ის grant გამყიდველს PostgREST-ით
--    პირდაპირ წერის უფლებას აძლევდა — free პაკეტის gate-ის (PDF ცოდნა მხოლოდ ფასიანზე)
--    და ტექსტის კონტროლის გვერდის ავლით.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- 1) revoke update on public.orders from anon, authenticated (+ სვეტის დონის status grant
--    ცხადად). SELECT / DELETE ნებართვები და RLS პოლისები ხელუხლებელია.
-- 2) shops: UPDATE grant ისევ იგივე სია, knowledge და knowledge_filename-ის გარეშე.
--    backend (shops.py upload_knowledge / clear_knowledge) ამ სვეტებს service client-ით
--    წერს, მფლობელობის RLS-ით შემოწმების შემდეგ.
--
-- ⚠️ გაშვების რიგი (RUN ORDER):
--    1. ჯერ backend-ის DEPLOY (ახალი კოდი knowledge-ს service client-ით წერს);
--    2. მერე PRE-CHECK ინფო query;
--    3. მერე ეს მიგრაცია;
--    4. ბოლოს ქვემოთ მოცემული ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (verification query).
--    ძველი backend + 0022 = knowledge-ის ატვირთვა/წაშლა "permission denied" (500).
--
-- ⚠️ ცხრილის დონის REVOKE სვეტის დონის ნებართვებსაც აუქმებს, ამიტომ ჯერ revoke,
--    მერე column grant (0015/0018-ის იგივე ფორმა). იდემპოტენტურია.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- PRE-CHECK (ინფორმაციული, გაუშვი ცალკე, მიგრაციამდე; მიგრაციას არ აბრკოლებს).
-- free პაკეტის მაღაზიები, რომლებსაც უკვე აქვთ knowledge — შესაძლოა PostgREST-ით
-- ჩაწერილი gate-ის გვერდის ავლით. გადაწყვეტილებას მფლობელი იღებს (დატოვოს/გაასუფთავოს).
--
--   select id, name, subscription_tier, knowledge_filename, length(knowledge) as chars
--   from public.shops
--   where knowledge is not null
--     and coalesce(subscription_tier, 'free') = 'free';
-- ----------------------------------------------------------------------------

begin;

revoke update on public.orders from anon, authenticated;
revoke update (status) on public.orders from anon, authenticated;

revoke update on public.shops from anon, authenticated;
revoke update (knowledge, knowledge_filename) on public.shops from anon, authenticated;
grant update (name, description, currency, bot_language)
  on public.shops to authenticated;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     has_column_privilege('authenticated','public.shops','knowledge','UPDATE')          as knowledge_upd,
--     has_column_privilege('authenticated','public.shops','knowledge_filename','UPDATE') as kfile_upd,
--     has_column_privilege('authenticated','public.shops','name','UPDATE')               as name_upd,
--     has_column_privilege('authenticated','public.shops','description','UPDATE')        as descr_upd,
--     has_column_privilege('authenticated','public.shops','currency','UPDATE')           as cur_upd,
--     has_column_privilege('authenticated','public.shops','bot_language','UPDATE')       as lang_upd,
--     has_column_privilege('authenticated','public.shops','subscription_tier','UPDATE')  as tier_upd,
--     has_column_privilege('authenticated','public.orders','status','UPDATE')            as ord_status_upd,
--     has_column_privilege('authenticated','public.orders','items','UPDATE')             as ord_items_upd,
--     has_table_privilege('authenticated','public.orders','UPDATE')                      as ord_tbl_upd,
--     has_table_privilege('anon','public.orders','UPDATE')                               as anon_ord_upd,
--     has_table_privilege('authenticated','public.orders','SELECT')                      as ord_sel,
--     has_table_privilege('authenticated','public.orders','DELETE')                      as ord_del,
--     has_table_privilege('service_role','public.orders','UPDATE')                       as svc_ord_upd,
--     has_column_privilege('service_role','public.shops','knowledge','UPDATE')           as svc_knowledge_upd;
--
-- სწორი შედეგი:
--   knowledge_upd=f, kfile_upd=f, name_upd=t, descr_upd=t, cur_upd=t, lang_upd=t,
--   tier_upd=f, ord_status_upd=f, ord_items_upd=f, ord_tbl_upd=f, anon_ord_upd=f,
--   ord_sel=t, ord_del=t, svc_ord_upd=t, svc_knowledge_upd=t
--
-- ხელით შემოწმება (გამყიდველის ანგარიშით, deploy-ის შემდეგ): PDF ცოდნის ატვირთვა/წაშლა
-- (ფასიან პაკეტზე), მაღაზიის სახელის/ენის შეცვლა და შეკვეთის სტატუსის შეცვლა მუშაობს.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK
--
-- ⚠️ ამის შემდეგ ისევ ღიაა: პირდაპირ PostgREST-ით orders.status-ის შეცვლა (მარაგის
--    გვერდის ავლით) და shops.knowledge-ის ჩაწერა (free gate-ის გვერდის ავლით).
--    backend-ის კოდს rollback არ სჭირდება (service client ორივე შემთხვევაში მუშაობს).
--
--   begin;
--   grant update (status) on public.orders to authenticated;
--   grant update (knowledge, knowledge_filename) on public.shops to authenticated;
--   commit;
-- ----------------------------------------------------------------------------
