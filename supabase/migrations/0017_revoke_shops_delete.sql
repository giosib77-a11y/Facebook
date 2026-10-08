-- ============================================================================
-- 0017: shops-ის DELETE ნებართვის მოხსნა anon/authenticated-დან (A-1)
--
-- ᲞᲠᲝᲑᲚᲔᲛᲐ
-- RLS პოლისი (0001) გამყიდველს საკუთარი `shops` მწკრივის წაშლის უფლებას აძლევს,
-- Supabase კი `authenticated`-ს ნაგულისხმევად აძლევს DELETE-ს ცხრილზე. ამიტომ
-- გამყიდველს საჯარო anon გასაღებით + საკუთარი JWT-ით შეეძლო პირდაპირ PostgREST-ზე
--   DELETE /rest/v1/shops?id=eq.<ჩემი>
-- გაეშვა და backend-ის გვერდის ავლით:
--   * products იშლება CASCADE-ით, მაგრამ Storage-ის ფოტოები (product-images/<shop_id>/*)
--     რჩება → კვოტის (FA-09) და ფოტოების გასუფთავების გვერდის ავლა, ობოლი ფაილები;
--   * `bot_customers` მრიცხველი (პაკეტის ლიმიტი) მაღაზიასთან ერთად იკარგება →
--     წაშალე და თავიდან შექმენი = კლიენტების ლიმიტის განულება.
--
-- ᲒᲐᲛᲝᲡᲐᲕᲐᲚᲘ
-- DELETE-ს ვურთმევთ anon/authenticated-ს. გამყიდველის UI-ში მაღაზიის წაშლა არ
-- არსებობს (არც backend endpoint, არც frontend-ის პირდაპირი Supabase გამოძახება —
-- გადამოწმებულია grep-ით). წაშლას აკეთებს მხოლოდ `DELETE /admin/shops/{id}`
-- (service_role), რომელიც ახლა Storage-ის საქაღალდესაც წმენდს.
-- SELECT / INSERT / UPDATE ნებართვები და RLS პოლისები ხელუხლებელია;
-- service_role-ის DELETE უფლება რჩება.
--
-- გაშვების რიგი: backend-ის deploy-ს არ ეყრდნობა — შეიძლება ნებისმიერ დროს
-- (მიგრაცია არაფერს არღვევს; Storage cleanup-იანი admin deploy-ც დამოუკიდებელია).
-- რეკომენდებული: ჯერ backend deploy, მერე ეს მიგრაცია.
--
-- გაშვება: Supabase → SQL Editor → ჩასვი → RUN. იდემპოტენტურია.
-- ============================================================================

begin;

revoke delete on public.shops from anon, authenticated;

commit;

-- ============================================================================
-- ᲨᲔᲛᲝᲬᲛᲔᲑᲐ (გაუშვი იმავე SQL Editor-ში)
--
--   select
--     has_table_privilege('anon','public.shops','DELETE')          as anon_delete,
--     has_table_privilege('authenticated','public.shops','DELETE') as auth_delete,
--     has_table_privilege('service_role','public.shops','DELETE')  as service_delete,
--     has_table_privilege('authenticated','public.shops','SELECT') as auth_select;
--
-- სწორი შედეგი: anon_delete = false, auth_delete = false,
--               service_delete = true, auth_select = true.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- ROLLBACK
--
-- ⚠️ ამის შემდეგ გამყიდველს ისევ შეეძლება მაღაზიის პირდაპირ წაშლა PostgREST-ით
--    (storage/კლიენტების მრიცხველის გვერდის ავლით).
--
--   begin;
--   grant delete on public.shops to authenticated;
--   commit;
--
-- (anon-ს DELETE თავდაპირველადაც RLS-ით იყო შეზღუდული; აუცილებელი არ არის.)
-- ----------------------------------------------------------------------------
