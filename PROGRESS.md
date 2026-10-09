# Progress

## Current Stage
Stage 12 — Live-მზადყოფნა: მესამე სრული აუდიტი (standard-reviewer, 2026-10-09; მფლობელის გადაწყვეტილება)

ID-ები S12-n; commit: `fix(scope): ... (S12-n)`. მიგრაცია `0024` — აგენტი წერს, **გაშვება მფლობელი, ხელით**.
Stage 11 — დასრულებულია (კოდი + deploy); მისი task-ები: `## Stage 11 — Done`. Stage 10 — `## Stage 10 — Done`.

<!-- Stage 10 header (ისტორია):

აუდიტი 2026-10-08 (standard-reviewer, ორი ნაწილი: A — isolation/auth/secrets, B — public/webhook/bot/uploads).
ID-ები (A-n / B-n) commit message-ში იწერება: `fix(scope): ... (A-1)`.
შენიშვნა: მიგრაციის ფაილს აგენტი წერს, **გაშვება — მფლობელი, ხელით** (Supabase SQL Editor),
backend-ის deploy-მდე ან მის შემდეგ — task-ში მითითებული რიგით.
-->

## Tasks
- [x] **S12-1 — should-fix (Live-მდე): image ჩამოტვირთვას მთლიანი deadline + მხოლოდ საკუთარი Storage URL** (აუდიტი #4, B-12-ის ნაწილი) · `services/facebook.py` (`download_image`, `is_own_storage_image_url`), `services/bot.py` (`_fetch_product_images`)
  - slow-drip `image_url` thread-ს წუთობით იკავებდა → threadpool-ის ამოწურვა. Fix: 15 წმ-იანი `time.monotonic` deadline; ბოტი საცნობარო ფოტოს მხოლოდ `<SUPABASE_URL>/storage/v1/object/public/product-images/` ბილიკიდან იღებს (UI-ში ფოტო მხოლოდ ატვირთვით → გარე URL ლეგიტიმური გზა არ არის; პირდაპირი PostgREST `image_url` გარე URL-ს ბოტი უგულებელყოფს). B-12-ის ნარჩენი (DNS rebinding, 100.64/10) ახლა მხოლოდ კლიენტის FB/IG CDN URL-ებს ეხება → Backlog-ში რჩება.
  - Verify: ტესტები (fake clock-ით slow-drip წყდება; გარე URL არ იწერება; supabase_url ცარიელი → უარი).
- [x] **S12-2 — should-fix: `enforce_bot_limit` სამივე downgrade გზაზე + ტესტები** (აუდიტი #1 + #5) · `services/bot_limits.py`, `api/shops.py`, `api/admin.py`
  - ადმინის tier-ცვლა/approve ზედმეტ ბოტს არ თიშავდა; გამყიდველის downgrade ერთადერთ მომუშავე ბოტს თიშავდა, თუ უფრო ძველი მაღაზიის ბოტი გამორთული იყო. Fix: ერთი helper (რჩება ჩართულებიდან ყველაზე ძველი `limit`); შეცდომა → 500 (აღარ ილექება). knowledge upload/clear ტესტებს `.eq("id")` assert დაემატა.
  - Verify: 9 ახალი ტესტი სამივე გზაზე (mutation-ით დადასტურდა: helper-ის გარეშე admin ტესტები ვარდება).
- [x] **S12-3 — should-fix: `upgrade_requests` — authenticated-ს INSERT მოხსნილია (migration 0024)** (აუდიტი #2 + nit `_cancel_pending_requests`) · `supabase/migrations/0024_*.sql`, `api/shops.py`
  - ბიზნეს-წესი: გამოწერა per-account → pending **per-account**: ახალი მოთხოვნა მფლობელის ყველა მაღაზიის ძველ pending-ს აუქმებს; ჩაწერა service client-ით RLS-ownership-ის შემდეგ; rate limit 10/სთ/IP; `_cancel_pending_requests` შეცდომას აღარ ყლაპავს. 0024: revoke + policy drop + partial unique (მაქს. ერთი pending მაღაზიაზე, დუბლიკატებს cancelled-ზე გადაიყვანს). Decision Log-ში ჩაწერილია.
  - Verify: 5 ახალი ტესტი; SQL verification query მიგრაციაში (**გაშვება — მფლობელი**).
- [x] **S12-4 — `CLIENT_IP_TRUSTED_HOPS` production-ში სავალდებულო** · `config.py`, `core/ratelimit.py`, `.env.example`
  - default (1) ამოღებულია (`None`); production-ში ცარიელი/<1 → startup `RuntimeError`. ⚠️ Render-ზე უკვე `=3` (Stage 10) — deploy-მდე გადაამოწმე, თორემ სერვერი არ ადგება.
  - Verify: ტესტები (პროდაქშენში აკლია → სახელი სიაში; 0 → invalid; dev-ში არ მოითხოვება).
- [x] **S12-5 — docs nits ერთად** · `CLAUDE.md`, `PROJECT.md`, `README.md`, `.env.example`
  - CLAUDE.md: ტესტების რაოდენობა, მიგრაციის შემდეგი ნომერი; PROJECT.md: მიგრაციების დიაპაზონი, Cloudflare → Render, Accepted Risks #18, Open Questions; README: მიგრაციების რაოდენობა + 0024, handoff-ის ცხრილი (`bot_conversations`), `CLIENT_IP_TRUSTED_HOPS`, `ADMIN_USER_IDS`; `.env.example`: `ADMIN_USER_IDS`, `CLIENT_IP_TRUSTED_HOPS`, `CLIENT_IP_DEBUG`, `LOG_LEVEL`, `PAYMENT_*`.
  - Accepted Risks-ში ჩაემატა: kill-switch (#3), `SHOP_ORDERS_PER_HOUR`, Supabase client ყოველ მოთხოვნაზე.

### Stage 12 — Deploy plan (მფლობელი; აგენტი remote-ზე არაფერს უშვებს)
> რიგი მნიშვნელოვანია: 0024 backend-ის **შემდეგ** (ძველი backend + 0024 = „პაკეტის მოთხოვნა" 403/500).
0. **Deploy-მდე (არჩევითი, SELECT):** `select count(*) from products where image_url is not null and image_url not like '<SUPABASE_URL>/storage/v1/object/public/product-images/%';` — რაც > 0, იმ პროდუქტების ფოტო ბოტს ვიზუალურ შედარებაში აღარ მიიღებს (S12-1).
1. **Render env-ის შემოწმება deploy-მდე:** `CLIENT_IP_TRUSTED_HOPS=3` დაყენებულია? (S12-4: გარეშე ახალი ვერსია არ ადგება; Render წინა ვერსიას დატოვებს.) დანარჩენი შვიდი secret უკვე არის.
2. `agent-system` → `main` merge + push → Render auto-deploy. ლოგში: სერვერი ადგა, `/health` 200.
3. 0024-ის PRE-CHECK (დუბლიკატი pending-ები; ინფორმაციული), მერე `supabase/migrations/0024_upgrade_requests_backend_only.sql` SQL Editor-ში.
4. 0024-ის verification query → `f, t, f, 0, 1`.
5. ხელით ბრაუზერში: (ა) პანელიდან „პაკეტის მოთხოვნა" → 200, ადმინში pending ჩანს; (ბ) მეორე მოთხოვნა სხვა პაკეტზე → პირველი cancelled; (გ) ადმინი standard→free ორ-ბოტიან ანგარიშზე → ახალი ბოტი ითიშება, ძველი რჩება; (დ) პროდუქტის ფოტო (საკუთარი Storage) ბოტის „რა ღირს ეს?" ფოტო-შეკითხვაზე ისევ მუშაობს.
6. `0023` (S11-7) თუ ჯერ არ გაშვებულა — იგი დამოუკიდებელია, ნებისმიერ დროს.

## Deploy plan
> მფლობელის გადაწყვეტილება (2026-10-08): ყველა task-ის შემდეგ ერთი დაგეგმილი deploy. სტატუსი განახლებულია მფლობელის ინფორმაციით.

### ✅ შესრულებულია (მფლობელი, ლაივ ბაზაზე)
- `supabase/checks/check_0014_0016.sql` → ყველა 32 შემოწმება `ok=true` — 0014–0016 ლაივზე გაშვებული იყო.
- მიგრაციები **0017, 0018, 0019, 0020** გაშვებულია ლაივ ბაზაზე (Supabase migration history-ში ჩაიწერა): PRE-CHECK-ები (0 მწკრივი) და თითოეულის verification query — ყველა შედეგი მოსალოდნელს ემთხვევა.
- **T20 (ერთჯერადი მარაგის გასწორება) არ დასჭირდა:** სატესტო შეკვეთები წაიშალა, `orders` ცხრილი ცარიელია. `supabase/one-off/release_legacy_new_order_stock.sql` რჩება მხოლოდ როგორც სათადარიგო.
  ⚠️ პირობა: თუ deploy-მდე ძველმა backend-მა ახალი შეკვეთა მიიღო (ძველი წესით მარაგი უკვე დაკლებულია), `orders` ცხრილი deploy-ის შემდეგ ისევ შეამოწმე (`select count(*) from public.orders;`); თუ > 0 და ისინი `new`-ია deploy-მდე შექმნილი — გამოიყენე ის სკრიპტი. ცარიელი ცხრილი = არაფერი გასაკეთებელია.
- ⚠️ გაითვალისწინე: მიგრაციები ახლა **ძველ backend-ზე** მუშაობს deploy-მდე. გადამოწმებულია კოდით, რომ ძველი backend თავსებადია (orders UPDATE მხოლოდ `status`, delete მხოლოდ done/cancelled, upgrade_requests იგივე ველები).

### ✅ Backend deploy (მფლობელი, ლაივზე)
- `832997f` live. `CLIENT_IP_TRUSTED_HOPS=3`; `CLIENT_IP_DEBUG=false` (გამორთულია).
- ლაივ XFF ჯაჭვი (მფლობელის ინფორმაციით): `<ყალბი>, <კლიენტი>, <Render-ის Cloudflare>, <Render-ის შიდა>` → კლიენტი მარჯვნიდან მე-3 პოზიციაზეა. `resolved` სწორად აჩვენებს კლიენტის IP-ს და ყალბ XFF-ს ანგარიშში არ აგდებს. (მფლობელმა შეამოწმა; აგენტს ლაივზე არაფერი გაუშვია.)
- შესრულებულია Deploy plan-ის ნაბიჯები: 1 (`CLIENT_IP_DEBUG`), 2 (merge + deploy), 3 (hops-ის შემოწმება), 4 (debug გამორთვა).

### ⏳ დარჩენილი
5. deploy-ის შემდეგ ხელით შემოწმება:
   - ✅ (მფლობელი) login, ფოტოს ატვირთვა, საჯარო შეკვეთა (201), ბოტი, admin.
   - ⏳ **ღია (მფლობელის თქმით ერთადერთი): მარაგის შემოწმება** — საჯარო შეკვეთის შექმნა მარაგს არ ცვლის; პანელში `new → processing` მარაგს აკლებს; `processing → cancelled` აბრუნებს. (სადაც 409 არასაკმარის მარაგზე და `new/processing`-ის წაშლა → 409 — ეს ორი მფლობელს ცალკე არ დაუდასტურებია.)
   - ✅ (მფლობელი, 2026-10-09) დამატებით დადასტურებულია: `new → cancelled` და მოძველებული სტატუსი (409/`STATUS_CHANGED`) — smoke SQL-ის შემოწმებები 4 და 8 ლაივ ბაზაზე; `/status` → `env=production` (შემოწმდა 2026-10-08); GitHub CI მწვანეა; T20-ის სათადარიგო პირობა დახურულია (deploy-მდე `orders` ცარიელი იყო).
   - ⏳ შეუმოწმებელი (მფლობელის გადაწყვეტილებით რჩება): **S11-2** (ორი გვერდის წვდომით connect-ის უარი ბრაუზერში), **S11-3** (Gemini timeout-ის ქცევა ლაივზე); `new/processing`-ის წაშლა → 409 და `ig_taken` ბრაუზერში ცალკე დადასტურებული არ არის.
6. **საგანგებო (2026-10-16):** თუ `gemini-2.5-flash` გაითიშა, Render-ზე `GEMINI_MODEL=gemini-3.5-flash` + restart. ⚠️ 3.5-ზე thinking-ის გამო პასუხები იჭრება `max_output_tokens=800`-ზე (ტესტზე 4/10) — ბოლო გამოსავალია (Backlog T12).
7. **key-ების როტაცია:** ✅ `FB_APP_SECRET` — შეცვლილია; ✅ Supabase — legacy key-ები გამორთულია, 401 დადასტურებულია (T23); ✅ `FB_TOKEN_ENCRYPTION_KEY` — შეცვლილია (Render + ლოკალური `.env`), ერთადერთი Facebook/Instagram-მიბმული მაღაზია ხელახლა დაკავშირდა, ბოტი პასუხობს. ⏳ **ღია: Gemini key-ის როტაცია** — როდის, მფლობელი წყვეტს.
8. ✅ ლოკალურ `.env`-ში `APP_ENV=development` (მფლობელმა დაადასტურა).

### 🔑 Supabase API key-ების გადასვლა (T23) — ზუსტი რიგი
> key-ების მნიშვნელობებს მფლობელი სვამს. **ძველი service_role გაჟონა → ის ძალაში რჩება, სანამ legacy key-ები არ გამოირთვება (ნაბიჯი K7). არ გააჭიანურო.**
> ახალი env სახელები: `SUPABASE_PUBLISHABLE_KEY` (`sb_publishable_…`, ძველი: `SUPABASE_ANON_KEY`), `SUPABASE_SECRET_KEY` (`sb_secret_…`, ძველი: `SUPABASE_SERVICE_ROLE_KEY`). ახალი სახელი უპირატესია; ძველი მუშაობს fallback-ად. ცარიელ-მაგრამ-არსებული ახალი ცვლადი ძველს **ფარავს** → rollback-ისას ახალი ცვლადი **წაშალე**, ცარიელზე ნუ დააყენებ.
> სად ვიღებთ: Supabase Dashboard → Project Settings → API Keys → ახალი tab (Publishable / Secret). Secret key-ს არ ვაჩვენებთ არსად, არ ვაგზავნით.

- **K1. კოდის deploy** ✅ (მფლობელი) (merge `agent-system` → `main` + push). ძველი env ჯერ არ იცვლება — ბოლო ეტაპზე ცვლილება უხილავია (fallback). frontend `config.js`-ში ახლა ველი უკვე `SUPABASE_PUBLISHABLE_KEY`, მნიშვნელობა ჯერ ძველი anon JWT. შემოწმება: საიტი/პანელი/ბოტი ისევ მუშაობს.
- **K2. Render env:** ✅ დაამატე `SUPABASE_SECRET_KEY=sb_secret_…` და `SUPABASE_PUBLISHABLE_KEY=sb_publishable_…` (ძველებს ჯერ ნუ წაშლი) → Render restart.
- **K3. შემოწმება backend-ზე ✅ (მფლობელი: ფოტოს ატვირთვა 200, შეკვეთა 201, ლოგში შეცდომა არ არის) ახალი key-ებით** (ეს არის ერთადერთი ადგილი, სადაც `sb_secret_`-ის რეალური მუშაობა დგინდება — offline ვერ დადასტურდა):
  - პანელში login, მაღაზიების/პროდუქტების სია (publishable + მომხმარებლის JWT, RLS);
  - ფოტოს ატვირთვა/წაშლა (Storage, secret key);
  - საჯარო შეკვეთა `order.html`-იდან (service client);
  - Messenger-ში ბოტი პასუხობს (webhook → service client);
  - admin პანელი იხსნება (service client);
  - Render-ის ლოგში `Invalid API key`/`401`/`permission denied` არ არის.
  თუ რამე ცუდადაა — **rollback:** წაშალე `SUPABASE_SECRET_KEY` და `SUPABASE_PUBLISHABLE_KEY` Render-ზე (ძველი სახელები გააგრძელებს მუშაობას), restart.
- **K4. ლოკალური `.env`:** ✅ (ახალ სახელებზეა) იგივე ორი ცვლადი ახალი სახელებით (ძველი ორი ხაზი წაშალე); ლოკალური backend-ი production Supabase-ს უკავშირდება — მხოლოდ შენ გაუშვი.
- **K5. frontend:** ✅ `public/config.js` და `dist/` განახლებულია `sb_publishable_…`-ით (commit agent-system-ზე; push/deploy და ქვემოთ ჩამოთვლილი ხელით შემოწმებები ჯერ მფლობელს ელის) — `frontend/public/config.js`-ში `SUPABASE_PUBLISHABLE_KEY`-ის მნიშვნელობა შეცვალე `sb_publishable_…`-ით (ეს key საჯაროა, git-ში ჩადება ნორმალურია) → `cd frontend && npm run build` → commit `public/config.js` + `dist/` → push. შემოწმება: login/logout, რეგისტრაცია, პაროლის აღდგენა (`reset.html`), `order.html` (მენიუ იტვირთება), admin.html.
- **K6. Render env-ის გასუფთავება:** ✅ (მფლობელი: ძველი ორი ცვლადი წაშლილია, deploy live, შეკვეთა 201 მხოლოდ ახალ key-ებზე) წაშალე `SUPABASE_SERVICE_ROLE_KEY` და `SUPABASE_ANON_KEY` → restart → K3-ის შემოწმება ხელახლა (დარწმუნდი, რომ ახალი სახელები ნამდვილად მუშაობს და fallback-ზე არ იყავი).
- **K7. legacy key-ების გამორთვა:** ✅ (მფლობელი: გამორთულია) Supabase Dashboard → Project Settings → API Keys → **Legacy API keys** → გამორთვა („Disable JWT-based API keys" / legacy anon & service_role). ეს ააქტიურებს გაჟონილი service_role-ის გაუქმებას. ეფექტი: ძველი anon/service_role JWT-ები აღარ მუშაობს; მომხმარებლების სესიის JWT-ები Auth-ისაა და არ ირღვევა. უკან დასაბრუნებელია Dashboard-იდან (დროებით, თუ რამე გაფუჭდა).
- **K8. შემოწმება K7-ის შემდეგ:** ✅ ძველი anon key-ით REST მოთხოვნა → 401 (მფლობელმა დაადასტურა; გაჟონილი service_role-ის ცალკე curl-ზე ინფორმაცია არ მიმიღია, მაგრამ legacy JWT key-ები სრულად გამორთულია) — იგივე სია, რაც K3 + ახალი მომხმარებლის რეგისტრაცია/login + admin. გაჟონილი service_role-ით სცადე ერთი read (curl `apikey: <ძველი>` → 401 უნდა იყოს) — ამით დაადასტურებ, რომ გაუქმდა.
- **K9. გაჟონვის შემდეგ:** გადახედე Supabase Logs/Auth-ს საეჭვო აქტივობაზე (უცნობი მომხმარებლები, მასობრივი წაკითხვა/წაშლა) იმ პერიოდში, როცა key ძალაში იყო; საჭიროებისას ეს ცალკე task იქნება.

### Stage 11 — Deploy plan
- ✅ **Stage 11 deploy დასრულდა (მფლობელი): `0d7a129` live** (`main` = `agent-system` = `0d7a129`; S11-1…S11-4, ბრენჩის წესი CLAUDE.md-ში). მიგრაცია 0021 ლაივ ბაზაზე უკვე გაშვებული იყო.
- **S11-1 (მიგრაცია `0021_change_order_status.sql`) ✅ ლაივ ბაზაზე გაშვებულია და შემოწმებულია (მფლობელი): 1 ფუნქცია, `security_definer=false`, EXECUTE მხოლოდ `postgres` და `service_role`. დარჩა: backend deploy + ქვემოთ ნაბიჯი 4 (ხელით შემოწმება). (ორიგინალი რიგი/პროცედურა:** რიგი — **ჯერ 0021, მერე backend deploy** (ძველი backend 0021-თან მუშაობს; ახალი backend 0021-ის გარეშე სტატუსის შეცვლა სუფთად 400-ს აბრუნებს, მონაცემები უცვლელია.)
  1. PRE-CHECK: `select proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and proname in ('decrement_stock','apply_stock_delta');` → 2 მწკრივი.
  2. გაუშვი `0021_change_order_status.sql` (იდემპოტენტურია).
  3. Verification: `select p.proname, p.prosecdef as security_definer, coalesce(array_to_string(p.proacl, E'
'),'(PUBLIC-საც აქვს!)') as acl from pg_proc p join pg_namespace ns on ns.oid=p.pronamespace where ns.nspname='public' and p.proname='change_order_status';` → 1 მწკრივი, `security_definer=false`, acl-ში `service_role=X/…` და **არა** `=X/…`, `anon=X/…`, `authenticated=X/…`.
  3b. ✅ **გაშვებულია ლაივზე (მფლობელი): `SMOKE OK — rolled back`, სატესტო მონაცემი 0.** **Smoke-ტესტი (S11-4, გაუშვი deploy-მდე, 0021 უკვე ლაივზეა):** SQL Editor-ში ჩასვი მთელი `supabase/checks/smoke_change_order_status.sql` → RUN. რედაქტორი აჩვენებს „შეცდომას" — ეს ნორმალურია: `SMOKE OK — rolled back` = 12-ვე შემოწმება გავიდა და ბაზაში არაფერი დარჩა (ტრანზაქცია ბათილდება); `SMOKE FAIL: …` = ტექსტი დააკოპირე და deploy გააჩერე; `SMOKE SKIP: no auth.users row` = უნდა არსებობდეს ერთი მომხმარებელი; სხვა შეცდომა (not-null/check/function does not exist) = სქემა/0021 განსხვავდება, ესეც rollback-დება. არჩევითი შემოწმება: `select count(*) from public.shops where name like '\_\_SMOKE\_\_%';` → 0. ⚠️ ფაილი არასდროს გაშვებულა — პირველი გაშვება შენთან.
  4. ✅ (მფლობელი, ლაივზე) პანელში მარაგი: 102 → `processing` 100 → `cancelled` 102; ✅ `new → cancelled` (მარაგი უცვლელი) და მოძველებული სტატუსი → `STATUS_CHANGED` — smoke SQL-ის შემოწმებები 4 და 8.
- **S11-3:** ახალი არჩევითი env `GEMINI_TIMEOUT_SECONDS` (default 20 წმ; ბიუჯეტი ყველა retry-ზე ჯამში 45 წმ). დამატებითი ნაბიჯი არ სჭირდება, ერთ deploy-ში მიჰყვება. შემოწმება: ბოტი ჩვეულებრივად პასუხობს; timeout-ის ქცევა (fallback პასუხი) ლაივზე რეალურად არ გამოცდილა.
- **S11-2:** დამატებითი ნაბიჯი არ სჭირდება (backend + `dist/` ერთ deploy-ში). შემოწმება: ორი გვერდის წვდომით connect → ფანჯარაში შეტყობინება „თავიდან მიაბით…"; ერთი გვერდით → ჩვეულებრივად.

### 🚦 Live-მდე აუცილებელი (მფლობელის სია, 2026-10-09)
> ეს ნაბიჯები ჯერ არ არის შესრულებული/დადასტურებული, თუ სხვაგვარად არ წერია. "Live" = Meta App Live mode + რეალური გამყიდველები.
0. **Meta Graph API `v21.0` მოქმედებს 2027-01-21-მდე** (`FB_GRAPH_VERSION`, `config.py`). ვადამდე განახლდეს ახალ ვერსიაზე — ტესტით (Graph mock-ტესტები + ლაივზე webhook/OAuth/გაგზავნის შემოწმება) და არა ბრმად.
1. **`PAYMENT_IBAN`** (მაგ. `GE00XX0000000000000000`, 22 სიმბოლო; სურვილისამებრ მიმღები) და **`PAYMENT_CONTACT`** (ელფოსტა/ტელეფონი, სადაც გამყიდველი ქვითარს გამოგზავნის) — Render env-ში. მფლობელი დააყენებს Live-მდე; დააყენების გარეშე გამყიდველი პაკეტის მოთხოვნისას placeholder-ს ხედავს (`Dashboard.jsx`). (Backlog #27)
2. **Render plan = Starter და არა Free.** Free instance უმოქმედობისას „იძინებს" (`DEPLOYMENT.md`): პირველ webhook-ზე პასუხი Meta-ს timeout-ს აღემატება და შეტყობინება იკარგება + მეხსიერებაში არსებული ლიმიტები/dedup (`_SEEN_MIDS`, rate-limit) ნულდება. შეამოწმე Dashboard → service → Instance Type = **Starter** (always-on) და რომ **ერთი instance**-ია (Scaling: 1) — Accepted Risks #6, #9 სწორედ ერთ instance-ს ეყრდნობა; >1 instance-ზე ისინი უქმდება.
3. **`CORS_ORIGINS=https://chatassist.ge`** Render-ზე (Accepted Risks #11).
4. **Gemini billing ჩართული** (free tier = 5 მოთხოვნა/წთ; ტრაფიკზე ბოტი 429-ს დააბრუნებს — `PROJECT.md` Constraints) + **Gemini key-ის როტაცია** (ღიაა, იხ. ზემოთ ნაბიჯი 7).
5. **Gemini მოდელი** — `gemini-2.5-flash` 2026-10-16-ს ითიშება: გადაწყვეტილება/საგანგებო ნაბიჯი 6 (Backlog T12).
6. ✅ **Stage 11-ის deploy** (`0d7a129` live). ხელით/ლაივზე დადასტურებული: მარაგი processing/cancelled-ზე (102 → 100 → 102), smoke SQL (`SMOKE OK`, შემოწმებები 4 და 8 ჩათვლით). შეუმოწმებელი (მფლობელის გადაწყვეტილებით): S11-2 ბრაუზერში, S11-3 ლაივზე.
7. ✅ **ნაბიჯი 5-ის ხელით შემოწმებები** — `/status` → `env=production` (2026-10-08), GitHub CI მწვანეა, `orders` ცარიელი იყო deploy-მდე (T20-ის სათადარიგო პირობა დახურულია).
8. **K9:** Supabase Logs/Auth-ის გადახედვა გაჟონვის პერიოდისთვის.
9. **Meta (README §2):** Business Verification ⏳ → App Review ⬜ → Development → Live ⬜. Review-ისთვის: Privacy/Terms/Data Deletion URL-ები და callback არსებობს (Accepted Risks #19).
10. **Supabase Pro (Free გეგმაზე backup-ები საერთოდ არ არის — Dashboard-ში დადასტურდა, მფლობელი).** Live-მდე გადადი Pro-ზე, რომ DB-ს ავტომატური ყოველდღიური backup ჰქონდეს; ახლა შეკვეთების, მარაგისა და გამყიდველების მონაცემის დაკარგვის შემთხვევაში აღდგენა შეუძლებელია. გადასვლის შემდეგ Dashboard → Database → Backups-ში შეამოწმე, რომ backup-ები ჩანს, და ერთხელ გადაამოწმე აღდგენის გზა (Pro-ზე PITR ცალკე add-on-ია, ვადა დამოკიდებულია გეგმაზე — დააზუსტე Dashboard-ში). ხარჯი ბიუჯეტში (~35₾/თვე, `DEPLOYMENT.md`) არ არის გათვალისწინებული — განაახლე `DEPLOYMENT.md`-ის ხარჯების ცხრილი.

### 🚀 S11-5 / S11-6 — Deploy plan (გარე აუდიტი #1–#3) — ✅ დასრულებულია (მფლობელი, ლაივზე)
1. ✅ Render-ის production-ის აუცილებელი ცვლადები: შვიდივე არსებობს (`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `GEMINI_API_KEY`, `FB_APP_SECRET`, `FB_VERIFY_TOKEN`, `FB_TOKEN_ENCRYPTION_KEY`).
2. ✅ Backend deploy: `955cde6` live, fail-closed startup გავიდა (სერვერი ადგება).
3. ✅ PRE-CHECK: free-პაკეტის მაღაზიებს `knowledge` არ აქვთ (გასასუფთავებელი არაფერია).
4. ✅ `0022_revoke_orders_knowledge_update.sql` ლაივ ბაზაზე გაშვებულია; verification 15/15 ემთხვევა მოსალოდნელს.
5. ✅ პანელში (მფლობელი, 0022-ის შემდეგ): knowledge POST/DELETE → 200; შეკვეთის სტატუსის PATCH → 200.
   - ℹ️ „მაღაზიის სახელის შეცვლა" პანელში არ არსებობს, ამიტომ ეს შემოწმება არ ეხება (backend-ში `auth.client`-ით მხოლოდ `bot_language` იწერება — `PATCH /shops/{id}`).
   - ⏳ ბოტის ენის შეცვლა (`bot_language`, ერთადერთი დარჩენილი `auth.client` ჩაწერა `shops`-ზე) 0022-ის შემდეგ ცალკე არ დადასტურებულა.

### Branch `agent-system` → `main`: მზადყოფნა (შემოწმდა 2026-10-08)
- `main` არ წასულა წინ (0 commit-ი `agent-system`-ის გარეშე) → merge fast-forward-ია; `git merge-tree` კონფლიქტს არ აჩვენებს. 27 commit, 42 ფაილი.
- სუფთა venv-ში CI-ის ნაბიჯები (`requirements.lock.txt` + `requirements-dev.txt` → `pip check` → `compileall` → `ruff check app tests` → `pytest -q`, `.env`-ის გარეშე): ყველა გავიდა, 174 passed. ლოკალური Python-ის ვერსია შეიძლება CI-ის 3.14.3-ისგან განსხვავდებოდეს — GitHub-ზე რეალური CI გაშვება: ✅ მწვანეა (მფლობელმა დაადასტურა 2026-10-09).
- Frontend: `npm run build` ახლა `frontend/dist/`-ს არ ცვლის (git status სუფთაა) → dist commit-შია და აქტუალურია.
- `git status` სუფთაა; secrets repo-ში არ ჩაგდებულა (T19: ტესტები `.env`-ს არ კითხულობენ).

## Backlog (needs user decision)
- **T12 (გადადებულია 2026-10-08) — Gemini მოდელი / AI provider-ის შეფასება.** მომავალი ეტაპი: AI provider-ის შეფასება — gemini-2.5-flash, gemini-3.5-flash (შეზღუდული thinking-ით) და Claude Haiku 4.5; შედარება ხარისხით, სიჩქარით და ფასით (თითო პასუხზე).
  - შედარების სკრიპტი არსებობს: `backend/scripts/compare_gemini_models.py` (პირველი შედეგი — Decision Log 2026-10). multimodal (ფოტოს გაგება) და `[[HANDOFF]]` ჯერ მხოლოდ ტექსტზეა შემოწმებული.
  - ⏰ დედლაინი: gemini-2.5-flash ითიშება 2026-10-16 — საგანგებო ნაბიჯი Deploy plan-შია.
- **T13 (გადატანილია Backlog-ში 2026-10-08) — ORIGIN_SECRET Render-ზე (მფლობელის ქმედება, კოდი არ სჭირდება)** · `backend/app/main.py:124-168`
  - წინაპირობა: Cloudflare ნამდვილად პროქსირებს `chatassist.ge`-ს (ნარინჯისფერი ღრუბელი). ინსტრუქცია — იხ. ჩატის ახსნა; ჩემგან Render-ზე არაფერი კეთდება.
  - Verify (მფლობელი): `curl -i https://<render-url>.onrender.com/status` → 403; `https://chatassist.ge/status` → 200; Messenger-ში ბოტი პასუხობს.
- [x] **T15 — წამკითხველი SQL: 0014–0016 გაშვებულია თუ არა ლაივ ბაზაზე** · `supabase/checks/check_0014_0016.sql`
  - მხოლოდ SELECT (არაფერს ცვლის); აგრეგირებს 0014/0015/0016 ფაილებში არსებულ verification query-ებს ერთ ფაილში,
    თითო შედეგი — ერთი მკაფიო სტრიქონი (migration, ok true/false, რა აკლია). **გაშვება — მფლობელი** (SQL Editor).
  - Verify: ფაილში არც ერთი DDL/DML (grep), query-ები ემთხვევა მიგრაციების ფაილებს.
- [x] **T16 — product-images ბილიკების სტრუქტურა და T5 cleanup-ის გასწორება** · `backend/app/api/products.py`, `backend/app/api/admin.py`
  - კოდიდან დადგინდეს, რა ბილიკებით ინახება ფოტო (`{shop_id}/...` ბრტყელი თუ ქვესაქაღალდეები); თუ ქვესაქაღალდეებია — `admin._remove_shop_images` რეკურსიულად წაშალოს.
  - Verify: ტესტი ქვესაქაღალდიანი fake-ით (თუ ბრტყელია — დადასტურება მოკლედ, ტესტი ბრტყელზე).
  - ✅ შედეგი: ბილიკი ყოველთვის ბრტყელია `{shop_id}/{uuid}.{ext}` (`products.py:179`, ერთადერთი upload) → cleanup-ის გასწორება არ სჭირდება. ისტორიული ხელით ატვირთული nested ობიექტები offline ვერ შემოწმდა.
- [x] **T14 — T2-ის შედეგი: ტექსტების გასწორება (frontend + delete_order)** · `frontend/src/**`, `backend/app/api/orders.py`
  - გამყიდველის პანელი / `order.html` შეიძლება ამბობდეს „მარაგი დაჯავშნილია / გაუქმებისას დაბრუნდება" — გადასამოწმებელია.
  - `delete_order`-ის 409 შეტყობინება და `DELETABLE_STATUSES` კომენტარი `new`-ისთვის ზუსტი აღარ არის (ტესტი d1 ამოწმებს ტექსტს).
  - Verify: grep ძველ ტექსტებზე; `npm run build` + `dist/` იმავე commit-ში; `pytest -q`.
  - მიზეზი: Cloudflare ახლა არ გამოიყენება; ნაცვლად — T17. დაბრუნდება Cloudflare-ის მომავალ ჩართვასთან ერთად.
### Stage 12 აუდიტიდან (nit, 2026-10-09)
- B-12-ის ნარჩენი (S12-1-ის შემდეგ): კლიენტის FB/IG CDN URL-ებზე DNS rebinding TOCTOU და `100.64/10` (CGNAT) `is_private`-ით არ იფარება → `ip.is_global` (`services/facebook.py` `_is_public_http_url`).
- ტესტი: `resolve_attention`-ის service update-ის `.eq("shop_id")` ფილტრის assert (knowledge-ისას დაემატა, აქ — არა).
- `get_current_admin`-ის tier/approve გზებზე ბოტის ხელით ჩართვა (`PATCH /admin/shops` `bot_enabled=true`) ჭერს არ ამოწმებს (ადმინის შეგნებული ქმედებაა).
- `docs`: README 157/175/201 ("19 მიგრაცია", „მარაგი ავტომატურად კლებულობს" → `processing`-ზე) — Stage 11 nit-ებიდან დარჩენილი.
- Finish-check (Stage 12): partial unique index (0024) მაღაზიაზეა, pending კი per-account → ორი პარალელური მოთხოვნა ერთი მფლობელის სხვადასხვა მაღაზიიდან ორ pending-ს დატოვებს; ერთი მაღაზიის პარალელურ მოთხოვნაზე მეორე 23505→500. იშვიათია; ნამდვილი per-account unique `owner_id` სვეტს (ან RPC-ს) მოითხოვს.
- Finish-check (Stage 12), გასწორდა: PROGRESS.md-ის დუბლირებული ბლოკი, `shop_usage` pending per-account, Storage prefix-ის ნორმალიზაცია (host-ის რეგისტრი/პორტი), CLAUDE.md CI-ის აღწერა, ზღვრის კომენტარის სიზუსტე.
### Stage 11 finish-check nits (2026-10-09, standard-reviewer)
- **❓ გადაწყვეტილება — გვერდების არჩევა (S11-2):** გამყიდველი, რომელსაც FB ანგარიშით 2+ გვერდი მართავს (standard/business — 2 ან ულიმიტო მაღაზია), ხელახალ connect-ზე უარს იღებს, მაშინაც კი, როცა არჩევანი ცალსახაა (მაღაზიას უკვე აქვს `facebook_page_id`, ან მეორე გვერდი ამავე მფლობელის სხვა მაღაზიაზეა მიბმული). მიმდინარე ქცევა — შენი გადაწყვეტილება (ა). შემოთავაზება: კანდიდატებიდან ამოვიღოთ ამავე მფლობელის სხვა მაღაზიებზე მიბმული გვერდები; თუ ამ მაღაზიის არსებული `facebook_page_id` სიაშია — ის; თუ ზუსტად 1 კანდიდატი რჩება — გამოვიყენოთ, სხვა შემთხვევაში `multiple_pages`. ⚠️ დაუდასტურებელია Meta-ს ქცევა: ხელახალ login-ზე გვერდის არჩევის დიალოგი ჩანს თუ არა, და გვერდის მონიშვნის მოხსნა სხვა მაღაზიაზე შენახულ token-ს აუქმებს თუ არა (თუ აუქმებს, ერთი FB ანგარიშით ორ მაღაზიას ორი გვერდით ვერ დააკავშირებ).
- 0021: დაბრუნების გზაზე `apply_stock_delta` დაუხარისხებელ items-ს იღებს, `decrement_stock` — დახარისხებულს → ორი შეკვეთის პარალელური საპირისპირო რიგით ცვლილებისას deadlock (40P01) შესაძლებელია (შედეგი: ტრანზაქცია უკან ბრუნდება, 400, მონაცემი არ ფუჭდება). Fix: ორივე გზას იგივე დახარისხებული სია.
- 0018: `authenticated`-ს `UPDATE(status)` ისევ აქვს, backend მას აღარ იყენებს → `revoke update (status) on public.orders from authenticated` (ახლა RPC ერთადერთი ჩამწერია; ზიანი მხოლოდ საკუთარ მარაგზე).
- 0021: `set search_path` არ არის (Supabase advisor: `function_search_path_mutable`; exploit არ არსებობს, ყველა მიმართვა schema-qualified-ია, INVOKER).
- `GEMINI_TIMEOUT_SECONDS` არ ვალიდირდება: 0/უარყოფითი → ყოველი მცდელობა 1 ms-ში ჩავარდება, ბოტი ყოველთვის fallback-ს გასცემს (`Field(gt=0, le=45)`).
- `bot.py`: httpx-ის timeout ფაზაზეა (connect/read/write/pool = 20 წმ), არა მთლიან მოთხოვნაზე → პათოლოგიურ შემთხვევაში ერთი მცდელობა 20 წმ-ს გადააჭარბებს; კომენტარი „ერთი მცდელობის timeout" არაზუსტია. 504 / DEADLINE_EXCEEDED `_TRANSIENT`-ში არ არის (S11-მდეც ასე იყო).
- 0021-ის header-ის კომენტარი ამბობს „500", რეალურად 400 (`orders.py`, test_s7) — დოკუმენტაცია.
- `FB_REDIRECT_URI` production-ის აუცილებელ სიაში არ არის (ცარიელი → OAuth connect გატეხილი, მაგრამ სერვერი ადგება); დაემატოს `missing_required_secrets()`-ს, თუ გინდა.
### Stage 11-ის აუდიტიდან (nit, 2026-10-09)
- **#15** საუბრის ისტორიის race: Messenger-ში ორი სწრაფი შეტყობინება პარალელურად მუშავდება, ორივე ძველ history-ს კითხულობს → ბოტის მეხსიერებიდან ერთი turn იკარგება (`webhook.py` `_save_turn`). კლიენტს ორივე პასუხი მიდის. Fix: append RPC.
- **#17** admin revenue `new` + `processing` + `done`-ს ერთად ითვლის (`admin.py` overview); B-1-ის შემდეგ `new` დაუდასტურებელია → ცალკე „დასრულებული" (done) და „მოლოდინში" მაჩვენებელი.
- **#24** stale `dist/`-ის რისკი: CI-ში `npm ci && npm run build && git diff --exit-code frontend/dist` (იაფია და დავიწყებულ build-ს იჭერს).
- **#27** `PAYMENT_IBAN`/`PAYMENT_CONTACT` default-ად placeholder ტექსტია (`config.py`) → გამყიდველი placeholder-ს ნახავს, თუ Render-ზე არ არის დაყენებული. მფლობელის შესამოწმებელი + production startup warning.
- **#1-ის ნარჩენი** Send API-ს ჩავარდნისას (მაგ. ვადაგასული token) კლიენტი პასუხს ვერ იღებს და ეს მხოლოდ ლოგში ჩანს (`webhook.py`) → საუბარი `needs_attention`-ად მოინიშნოს, რომ გამყიდველმა დაინახოს.
### Finish-check nits (2026-10-08, standard-reviewer)
- 0018-ის header-ის დასაბუთება ზუსტი არ არის: გამყიდველს PostgREST-ით `status`-ის პირდაპირ შეცვლა მაინც შეუძლია (`new → processing` დაკლების გარეშე, მერე API-ით `→ cancelled` = მარაგი +N). ზიანი მხოლოდ საკუთარ მარაგზე (`products.quantity`-საც ისედაც ცვლის, 0015). სრულად დახურვა: UPDATE-ის სრული revoke და status-ის ჩაწერა service-ით ownership-ის შემდეგ.
- `orders.py:410-411`: `_apply_stock_delta(+1)` შეცდომა სტატუსის შეცვლის შემდეგ 500-ს აბრუნებს — try/except + `logger.exception`.
- `facebook.py`: პარალელური connect-ის race-ზე unique violation `page_taken`-ად მიდის `ig_taken`-ის ნაცვლად; `any(...)` `.neq`-ის შემდეგ ზედმეტია.
- `admin.py:396-401`: storage cleanup-ის ციკლი — `break`, თუ `paths` არ შეცვლილა.
- `webhook.py`: `_RATE_PER_SHOP = 30/წთ` ყველა პაკეტისთვის ერთია; 5 spam PSID მაღაზიის ბოტს წუთით აჩერებს.
- README: 157 („19 მიგრაცია" → 20), 175/201 („მარაგი ავტომატურად კლებულობს" → `processing`-ზე).
### Nits (აუდიტიდან)
- ~~**A-9 / B-6**~~ — დაიხურა S11-6-ით (production fail-closed + ცარიელი secret-ის უარი + `"chatassist"` fallback ამოღებულია). ნარჩენი: `encrypt` `subscribe_page`-ის შემდეგაა (`api/facebook.py`).
  production-ში `FB_TOKEN_ENCRYPTION_KEY`/`FB_APP_SECRET` startup-ზე არ მოწმდება; `encrypt` `subscribe_page`-ის შემდეგაა (`api/facebook.py:253`).
- ~~**A-6**~~ — დაიხურა S11-5-ით (migration 0022: `knowledge*`-ზე UPDATE მოხსნილია, ჩაწერა მხოლოდ backend-ით service client-ით).
- **A-7** — `/admin/recovery` ადმინს recovery ბმულს აბრუნებს + `{e}` შეცდომაში (`admin.py:443-453`).
- **A-8** — upgrade request-ის resolve `status='pending'`-ს არ ამოწმებს (`admin.py:416-439`).
- **A-10** — მაღაზიის/პროდუქტის ლიმიტი TOCTOU (პარალელური POST-ით მცირე გადაჭარბება).
- **B-7** — არა-ASCII შეყვანა `hmac.compare_digest`-ს 500-ით აგდებს (`webhook.py:170`, `services/facebook.py:101,148`, `api/facebook.py:110`).
- **B-8a** — webhook batch-ში ერთი entry-ს exception დანარჩენებს კარგავს (`webhook.py:201-243`).
- **B-8b** — `_SEEN_MIDS` threadpool-იდან lock-ის გარეშე იცვლება (`webhook.py:61-77`).
- **B-10** — გვერდის „დაკავება" სხვის უფასო მაღაზიაზე; ნამდვილ მფლობელს მხოლოდ `page_taken` (`api/facebook.py:269-274`).
- **B-11** — popup-ის `message` listener origin/source-ს არ ამოწმებს (`frontend/src/panel/fbConnect.js:19-24`).
- **B-12** — SSRF: DNS rebinding TOCTOU, `is_private` არ ფარავს 100.64/10 → `is_global` + მხოლოდ საკუთარი Storage URL (`services/facebook.py:279-334`).
- **B-13** — კლიენტის ფოტოები `INLINE_IMAGE_BUDGET`-ს არ ემორჩილება (`webhook.py:313-317`).
- **B-14** — prompt extraction-ით PDF-ცოდნა ფაქტობრივად საჯაროა → გამყიდველს UI-ში გაფრთხილება (`bot.py:194-197`).
- Frontend lint (eslint) — არ არის; საჭიროა თუ არა?
- README მოძველებულია: `ADMIN_EMAIL` → `ADMIN_USER_IDS`, „ტესტები არ არსებობს", React 18 → 19, მიგრაციები 14 → 16.

### მფლობელის შესამოწმებელი (კოდით ვერ დადასტურდა)
- Render env: `APP_ENV=production`? (`GET https://chatassist.ge/status` → `env`), `ORIGIN_SECRET` დაყენებულია?
  (თუ არა — `CF-Connecting-IP` ყალბდება და IP-ლიმიტები უქმდება), `CORS_ORIGINS`, `FB_TOKEN_ENCRYPTION_KEY`.
- `product-images` bucket-ის policy-ები `storage.objects`-ზე (მიგრაციებში არ არის): შეუძლია თუ არა `authenticated`-ს პირდაპირ upload/delete?
- live DB-ში 0014 / 0015 / 0016 გაშვებულია? (verification query-ები ფაილებშია)
- Supabase Auth: anonymous sign-ins გამორთულია? email confirmation ჩართულია?
- ⏰ Gemini 2.5 Flash retires **2026-10-16** — რომელ მოდელზე გადასვლა?

## Run State
- Finish-check this stage: done (1 round; nit-ები გასწორდა, 1 Backlog-ში)
- Fix rounds this stage: 0/2
- Failed attempts: —

## Last Session
- Date: 2026-10-09
- Done: მესამე სრული აუდიტი (standard-reviewer) → Stage 12: S12-1…S12-5 (კოდი + მიგრაცია 0024 + docs); commit-ები `agent-system`-ზე, push არ გაკეთებულა.
- Verification: `pytest -q` → 263 passed (offline); `ruff check app tests` სუფთა. ვერ შემოწმდა: 0024 რეალურ Postgres-ზე, `sb_*` key-ები, ბრაუზერში upgrade-request/downgrade, ბოტის ფოტო-ნაკადი ლაივზე (Deploy plan-ის ნაბიჯი 5).
- Next: finish-check → მფლობელი: Stage 12 Deploy plan; Live-მდე აუცილებელი სია.

## Stage 11 — Done
- [x] **S11-1 — should-fix: შეკვეთის სტატუსი და მარაგი ერთ ტრანზაქციაში** (აუდიტი #2) · `backend/app/api/orders.py` (`update_order_status`), მიგრაცია `0021`
  - ახლა: სტატუსი `auth.client`-ით ახლდება, მარაგი ცალკე RPC-ით (`_take_stock` წინ, `_apply_stock_delta(+1)` შემდეგ). `processing/done → cancelled`-ზე, თუ სტატუსი შეიცვალა და მარაგის დაბრუნება ჩავარდა → შეკვეთა გაუქმებულია, მარაგი არ დაბრუნდა, პასუხი 500 (კომპენსაცია მხოლოდ აღების მხარეს არსებობს).
  - Fix: ერთი Postgres ფუნქცია (`change_order_status(order_id, expected_old, new)`) — სტატუსის ოპტიმისტური ჩაკეტვა + მარაგის აღება/დაბრუნება ერთ ტრანზაქციაში; იძახება service client-ით მხოლოდ `auth.client`-ით ownership-ის შემოწმების შემდეგ; `REVOKE EXECUTE … FROM public, anon, authenticated`. Python-ის კომპენსაციის ლოგიკა ქრება.
  - Verify: offline ტესტები (RPC-ის შეცდომის კოდები → 409/400), SQL verification query; მიგრაციას მფლობელი უშვებს.
- [x] **S11-2 — should-fix: Facebook OAuth ავტომატურად `pages[0]`-ს იღებს** (აუდიტი #8) · `backend/app/api/facebook.py` (connect callback)
  - რამდენიმე Page-ზე წვდომის მიცემისას შემთხვევითი პირველი მიება მაღაზიას → ბოტი არასწორ გვერდზე პასუხობს.
  - ✅ გადაწყვეტილება (მფლობელი, 2026-10-09): ვარიანტი (ა) — >1 გვერდზე უარი, შეტყობინებით: „თავიდან მიაბით და Facebook-ის ფანჯარაში მონიშნეთ მხოლოდ ის გვერდი, რომელზეც ბოტი გინდათ". backend + ახალი reason frontend-ში (`fbConnect.js`) + `npm run build`.
  - Verify: ტესტი 0/1/2+ გვერდზე.
- [x] **S11-3 — should-fix: Gemini-ს გამოძახებას timeout არ აქვს** (აუდიტი #21) · `backend/app/services/bot.py` (`get_bot_reply`)
  - `genai.Client` `http_options` timeout-ის გარეშეა; ჩამოკიდებული გამოძახება webhook-ის threadpool worker-ს უსასრულოდ იკავებს (4 მცდელობაც დამატებით), კლიენტი პასუხს ვერ იღებს.
  - Fix: `HttpOptions(timeout=…)` (მაგ. 25 წმ) + მთლიანი ბიუჯეტი retry-ებით ≤ ~45 წმ; timeout → არსებული fallback პასუხი.
  - Verify: ტესტი — timeout-ის exception → fallback; retry-ების ბიუჯეტი.
- [x] **S11-4 — should-fix (finish-check): 0021-ის მარაგის წესებს DB-ის დონეზე ტესტი არ აქვს** · `supabase/checks/smoke_change_order_status.sql`
  - მარაგის ბიზნეს-წესები ახლა მხოლოდ plpgsql-შია (0021); offline ტესტები RPC-ს mock-ით ცვლიან და მხოლოდ Python-ის მხარეს ამოწმებენ. წესი (B-1: `new` მარაგს არ ეხება; F-06: cancelled→processing აკლებს; done/processing→cancelled აბრუნებს; წაშლილი პროდუქტი გამოტოვება; INSUFFICIENT_STOCK/STATUS_CHANGED და rollback) რეალურ Postgres-ზე არასდროს გამოცდილა.
  - Fix: checked-in smoke SQL, რომელსაც მფლობელი უშვებს SQL Editor-ში: ერთი `DO` ბლოკი, რომელიც დროებით ქმნის სატესტო მონაცემს (არსებული auth user + ახალი shop/products/orders), ასრულებს გადასვლებს `change_order_status`-ით, ამოწმებს მარაგს/სტატუსს და **ყოველთვის ბოლოს exception-ს აგდებს** (წარმატებაზე ტექსტი `SMOKE OK`, ჩავარდნაზე `SMOKE FAIL: …`) — exception ტრანზაქციას ბათილს ხდის, ამიტომ ბაზაში არაფერი რჩება.
  - Verify: SQL-ის ხელით გადაკითხვა სქემასთან (NOT NULL სვეტები, FK, CHECK-ები 0016/0018/ trigger-ები); რეალური გაშვება — მფლობელი.
- [x] **S11-5 — should-fix (გარე აუდიტი #1 + #2): `authenticated`-ს `orders` და `shops.knowledge*`-ზე UPDATE უფლება · migration `0022`** · `supabase/migrations/0022_*.sql`, `backend/app/api/shops.py`
  - ✅ გადაამოწმდა კოდში: (1) `orders`-ზე `auth.client` UPDATE არსად გამოიყენება (მხოლოდ select/delete; სტატუსს RPC `change_order_status` ცვლის service client-ით) და frontend პირდაპირ Supabase-ს არ იძახებს → `UPDATE(status)` (0018) ზედმეტია; PostgREST-ით პირდაპირი `status`-ის შეცვლა RPC-ს გვერდს უვლის და მარაგს ბერავს. (2) `shops.knowledge/knowledge_filename`: frontend პირდაპირ არ წერს, **მაგრამ backend წერს** — `upload_knowledge` და `clear_knowledge` (`shops.py` ~441, ~454) `auth.client`-ით, ე.ი. მხოლოდ 0015-ის revoke backend-ს გატეხავდა.
  - Fix: (ა) backend: ორივე endpoint ჩაწერას ამჟამად ინახავს service client-ით **მფლობელობის RLS-ით (`auth.client` select) შემოწმების შემდეგ** (`clear_knowledge`-ს ამ შემოწმებას დავუმატებთ); free პაკეტის gate ინარჩუნებს. (ბ) migration `0022`: `revoke update on public.orders from authenticated` + `shops`-ზე `revoke update … from authenticated; grant update (name, description, currency, bot_language) …` (knowledge სვეტები გარეშე; დანარჩენი სვეტები 0015-ის იგივეა). PRE-CHECK/ინფო query: free-პაკეტის მაღაზიები, რომლებსაც უკვე აქვთ `knowledge` (შესაძლოა PostgREST-ით ჩაწერილი).
  - ⚠️ **გაშვების რიგი: ჯერ backend deploy, მერე 0022** (პირიქით knowledge-ის ატვირთვა/წაშლა 4xx-ს დააბრუნებს მიგრაციის გაშვებიდან deploy-მდე). ძველი backend + 0022 = გატეხილი knowledge.
  - Verify: ტესტები (knowledge endpoint-ები ownership-ით 404-ს აბრუნებენ სხვის მაღაზიაზე და ჩაწერა service client-ით; free gate), SQL verification query (`has_table_privilege`/`has_column_privilege`).
- [x] **S11-6 — should-fix (გარე აუდიტი #3): production-ში აუცილებელი secrets fail-closed** · `backend/app/config.py`, `main.py`, `app/api/facebook.py`, `app/services/facebook.py`
  - ✅ გადაამოწმდა: ცარიელი `FB_APP_SECRET` → `verify_signature`, `parse_signed_request`, `sign_state` HMAC-ს **ცარიელ key-ზე** ითვლიან (გაყალბებადია: webhook-ის ხელმოწერა, data-deletion callback, OAuth state); `_deletion_secret()` ცარიელზე `"chatassist"` fallback-ს იყენებს (გამოცნობადი); production startup-ზე secrets არ მოწმდება (`FB_TOKEN_ENCRYPTION_KEY`-ის გარეშე შეცდომა მხოლოდ პირველ connect-ზე — ჩუმი არასრული გაშვება).
  - Fix: (ა) production startup-ზე აუცილებელი სია — `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `GEMINI_API_KEY`, `FB_APP_SECRET`, `FB_VERIFY_TOKEN`, `FB_TOKEN_ENCRYPTION_KEY` (+ Fernet-ფორმატის ვალიდაცია): გარეშე `RuntimeError` სახელების სიით (ღირებულებების გარეშე) → სერვერი არ ადგება. dev/test-ზე არ მოქმედებს. (ბ) ფუნქციებში თავდაცვა: `verify_signature`/`parse_signed_request`/`sign_state` ცარიელ secret-ზე უარს ამბობენ (False/None/RuntimeError); `_deletion_secret()` ცარიელზე RuntimeError და არა `"chatassist"`. (გ) ახლა შესაძლებელია ტესტი „ცარიელი secret → 403" (T11-ის შენიშვნა).
  - ⚠️ **deploy-მდე** დარწმუნდი, რომ Render-ზე ყველა ზემოთ ჩამოთვლილი დაყენებულია (ახალი სახელებით Supabase-ისთვის), სხვაგვარად deploy ვერ ადგება (Render წინა ვერსიას დატოვებს). ADMIN_USER_IDS ცარიელი იყოს თუ არა — უკვე fail-closed და არ მოწმდება.
  - Verify: ტესტები production/development ორივე რეჟიმში; backlog A-9/B-6 დაიხურება (A-6 — S11-5).

- [x] **S11-7 — should-fix (მესამე გარე აუდიტი): NaN/Infinity ფასი, არამთელი მარაგი იმპორტში, CI/docs** · `models/product.py`, `models/order.py`, `services/import_products.py`, migration `0023`, `.github/workflows/ci.yml`, `README.md`, `backend/.env.example`
  - API: Infinity ფასი გადიოდა (NaN — არა); იმპორტი იღებდა `nan`/`inf`/`1e999` ფასს, `2.5` მარაგს ჩუმად აკეცავდა 2-მდე, `inf` მარაგი 500-ს (OverflowError) იძლეოდა. DB: `price >= 0` NaN-ს უშვებს → `0023` (`< 'Infinity'`, products + orders.total). Fix: `allow_inf_nan=False`, `math.isfinite`, მწკრივის ნომრით შეცდომა.
  - CI: frontend job (`npm ci` + build + `git diff --exit-code -- dist`), `pip-audit -r requirements.lock.txt`, `permissions: contents: read`. Render build → `requirements.lock.txt`. Docs: `ADMIN_USER_IDS`, ტესტების აღწერა.
  - ⚠️ მფლობელს: `0023` გაუშვი ხელით (PRE-CHECK ფაილის თავშია). Render Build Command უკვე `pip install -r requirements.lock.txt` იყო (Root Directory = backend) — ცვლილება არ დასჭირდა. CI-ის ახალი ნაბიჯები (pip-audit, frontend job) GitHub-ზე ჯერ არ გაშვებულა.

## Stage 10 — Done
- [x] **T1 — Minimal lint setup (backend)** · infra (verify.sh CHECKS: ruff + pytest დამატებულია, hook-ით შემოწმებული)
  - ruff ჯერ არ არის; ტესტები არის (114, offline, CI-ში).
  - `ruff` → `backend/requirements-dev.txt`; მინიმალური კონფიგი (`E`, `F` წესები) `backend/pyproject.toml`-ში ან `ruff.toml`-ში;
    არსებული დარღვევები გასწორდეს ან ცხადად გამოირიცხოს; CI-ში ნაბიჯი `ruff check app tests`.
  - `.claude/hooks/verify.sh` → CHECKS: ruff + pytest (მფლობელის თანხმობით).
  - Verify: `ruff check` სუფთაა, `pytest -q` გადის.
- [x] **T2 — B-1 (critical): ყალბი საჯარო შეკვეთებით მარაგის განულება** · `backend/app/api/orders.py:203-364`
  - ✅ გადაწყვეტილება (მფლობელი, 2026-10-08): ვარიანტი (გ) — მარაგი იკლებს **მხოლოდ `new → processing` გადასვლისას**;
    დამატებით **IP-ზე დღიური ლიმიტი** საჯარო შეკვეთებზე.
  - შედეგები, რაც ამ ცვლილებას თან მოჰყვება (გასათვალისწინებელი):
    - `create_order` აღარ იძახებს `decrement_stock`-ს; `new` შეკვეთის გაუქმებისას მარაგი **არ ბრუნდება** (არაფერი ჩამოვრიცხულა).
    - `new → processing`: ატომური დაკლება; თუ მარაგი არ ჰყოფნის → 409 + გასაგები შეტყობინება გამყიდველს.
    - `processing/done → cancelled` აბრუნებს მარაგს (როგორც ახლა); F-06 reopen-ის ლოგიკა ახალ მდგომარეობებს მოერგოს.
    - `public-menu` / ბოტი აჩვენებს რეალურ მარაგს, `new` შეკვეთები მარაგს აღარ ამცირებს → შეიძლება overselling `new`-ში (მისაღებია, გამყიდველი ადასტურებს).
    - IP-ლიმიტი in-memory-ია (deploy-ზე ნულდება) და **სანდოა მხოლოდ სწორი `CLIENT_IP_TRUSTED_HOPS`-ით (იხ. T17)**.
  - Verify: ტესტები — შეკვეთა მარაგს არ ცვლის; processing-ზე იკლებს; არასაკმარისი მარაგი → 409; cancel processing-იდან აბრუნებს;
    IP-ის დღიური ლიმიტი → 429.
- [x] **T3 — A-4 (hardening, დაბალი): `APP_ENV` default fail-open** · `backend/app/config.py:19`
  - მფლობელმა დაადასტურა: Render-ზე `APP_ENV=production` (`/status` → `env=production`), ე.ი. ლაივ-რისკი ახლა არ არსებობს.
    Fix მაინც ღირს (მომავალი გარემო/აღდგენა): default `production`; dev-ში `.env`-ით `APP_ENV=development`; tests/conftest ცხადად `development`.
  - Verify: ტესტი — env-ის გარეშე `is_production is True`; არსებული ტესტები გადის.
- [x] **T4 — B-2 (should-fix, high): xlsx-ის სვეტებით OOM** · `backend/app/services/import_products.py:62`
  - `iter_rows` `max_col`-ის გარეშე: 4.8KB ფაილი `dimension=A1:XFD…`-ით ≈ 660MB (გაზომილი ლოკალურად) → instance OOM.
  - Fix: `iter_rows(max_col=MAX_COLS)`; `load_workbook`-მდე zip-ის გაშლილი ზომის ჭერი.
  - Verify: ტესტი სინთეზური xlsx-ით (ფართო dimension) — სწრაფად ბრუნდება / ValueError.
- [x] **T5 — A-1 (should-fix): მაღაზიის პირდაპირი DELETE PostgREST-ით → storage კვოტის და კლიენტების მრიცხველის გვერდის ავლა** ·
  `supabase/migrations/0001_init.sql:104-107`, `backend/app/api/admin.py:381-383`
  - Fix: მიგრაცია `0017` — `revoke delete on public.shops from anon, authenticated`; `admin.delete_shop` შლის `product-images/{shop_id}/*`-საც.
  - Verify: ტესტი — admin delete იძახებს storage remove-ს; მიგრაციის verification query.
- [x] **T6 — A-2 (should-fix): `orders`-ზე column privileges / status CHECK არ არის** · `supabase/migrations/0002_orders.sql`
  - გამყიდველს PostgREST-ით შეუძლია `items`/`total` შეცვლა და მერე API-ით გაუქმება → მარაგის გაბერვა; აქტიური შეკვეთის წაშლა (F-07-ის გვერდის ავლა).
  - Fix: მიგრაცია — `revoke update, delete` + `grant update (status)`; `check (status in (...))`; delete policy მხოლოდ `done`/`cancelled`.
  - Verify: SQL verification query მიგრაციაში; API ტესტები გადის.
- [x] **T7 — B-3 (should-fix): webhook-ზე წუთობრივი ლიმიტი არ არის — ერთი კლიენტი ამოწურავს საერთო Gemini კვოტას / threadpool-ს** ·
  `backend/app/api/webhook.py:262-273`
  - Fix: in-memory ლიმიტი `(shop_id, psid)` (~6/წთ) და `shop_id` (~30/წთ); გადაჭარბება — ჩუმად გამოტოვება + log.
  - Verify: ტესტი — N+1-ე შეტყობინება `get_bot_reply`-ს არ იძახებს.
- [x] **T8 — A-3 (should-fix): `upgrade_requests` insert policy სვეტებს არ ზღუდავს** · `supabase/migrations/0005_upgrade_requests.sql:22-27`
  - Fix: მიგრაცია — WITH CHECK `status='pending' and resolved_at is null and requested_tier in (...)` + CHECK constraints.
  - Verify: SQL verification query.
- [x] **T9 — A-5 / B-9 (should-fix, low): `instagram_account_id` არ არის unique → IG DM შეიძლება სხვა tenant-ის მაღაზიას მიება** ·
  `supabase/migrations/0006_instagram.sql:11`, `backend/app/api/facebook.py:251-262`, `backend/app/api/webhook.py:209-213`
  - Fix: connect-ზე იგივე IG id სხვა მაღაზიიდან null-დება; მიგრაცია — partial unique index (`where instagram_account_id is not null`).
    ⚠️ მიგრაციამდე live DB-ში დუბლიკატები შესამოწმებელია (მფლობელი).
  - Verify: ტესტი connect-ზე; SQL verification query.
- [x] **T10 — B-4 (should-fix, low): საჯარო შეკვეთა იღებს `is_active=false` პროდუქტს** · `backend/app/api/orders.py:255-262`
  - Fix: `.eq("is_active", True)` `db_products` select-ში.
  - Verify: ტესტი — არააქტიური პროდუქტი → „ვერ მოიძებნა", მარაგი უცვლელი.
- [x] **T11 — B-5 (should-fix): webhook-ის ხელმოწერას ტესტი არ აქვს** · `backend/tests/`
  - Fix: ტესტები — სწორი ხელმოწერა → 200; არასწორი/არარსებული → 403. (ცარიელი secret → 403 ტესტი — მხოლოდ Backlog-ის A-9/B-6-ის გასწორების შემდეგ.)
  - Verify: `pytest -q`.
- [x] **T17 — should-fix: კლიენტის IP Render-ის სანდო header-იდან (CF-Connecting-IP გაყალბებადია)** · `backend/app/core/ratelimit.py`, `config.py`, `main.py`
  - მფლობელის გადაწყვეტილება (2026-10-08): Cloudflare არ გამოიყენება (chatassist.ge პირდაპირ Render-ზეა). `CF-Connecting-IP` ახლა კლიენტის მიერ ყალბდება → ყველა IP-ლიმიტი (T2, შეკვეთები) შემოსავლელია.
  - Render-ის დოკუმენტაცია ცალსახა არ არის: Render XFF-ს **არ ასუფთავებს, მხოლოდ ამატებს** (კლიენტის მიწოდებული მნიშვნელობა ინახება, Render ბოლოში ამატებს); Render-ის წარმომადგენელი 2021-ში წერს „first IP = real client", მაგრამ ეს მხოლოდ მაშინ სწორია, როცა კლიენტი XFF-ს არ აგზავნის.
    ⇒ სანდოა მხოლოდ XFF-ის **მარჯვენა მხარე** (Render-ის დამატებული ჩანაწერები), არა პირველი. ზუსტი hop-ის რაოდენობა (Render-ის edge + LB) დოკუმენტაციით ვერ დადასტურდა.
  - Fix: `CLIENT_IP_TRUSTED_HOPS` (int) — IP = XFF-ის მარჯვნიდან N-ური ჩანაწერი; კლიენტის `CF-Connecting-IP` სრულად იგნორირდება; დროებითი diagnostic (env-ით ჩასართავი), რომ მფლობელმა Render-ის ლოგში ნახოს რეალური XFF და N დააყენოს.
  - Verify: ტესტი — გაყალბებული `CF-Connecting-IP` და გაყალბებული XFF-ის მარცხენა ჩანაწერები IP-ს ვერ ცვლის; ლიმიტი სწორ bucket-ზე ითვლება.
- [x] **T18 — IG: მეორე მაღაზიის connect-ზე უარი (T9-ის გადაწყვეტილება)** · `backend/app/api/facebook.py`
  - მფლობელის გადაწყვეტილება: თუ IG ანგარიში უკვე სხვა მაღაზიასთანაა — connect უარს იღებს, მკაფიო შეტყობინებით („ანგარიში უკვე სხვა მაღაზიასთანაა, დაგვიკავშირდით"). T9-ის „სხვა მაღაზიიდან null-დება" ამოღდეს; webhook-ის ორაზროვნობის დაცვა და 0020 რჩება.
  - Verify: ტესტი — სხვა მაღაზიის IG id → უარი, არაფერი იცვლება; იგივე მაღაზიის ხელახალი connect გადის.
- [x] **T19 — should-fix: ტესტის ჩავარდნისას `Settings` repr secrets-ს ბეჭდავს** · `backend/tests/conftest.py`, `backend/app/config.py`
  - ტესტები ლოკალურ `.env`-ს კითხულობენ (conftest მხოლოდ `SUPABASE_URL`/`ANON_KEY`-ს ცარიელებს); ჩავარდნისას pytest ბეჭდავს `Settings(...)`-ს რეალური key-ებით (ერთხელ უკვე მოხდა hook-ის გამოტანაში).
  - Fix: conftest ყველა secret-ს (GEMINI_API_KEY, SUPABASE_SERVICE_ROLE_KEY, FB_APP_SECRET, FB_TOKEN_ENCRYPTION_KEY, FB_VERIFY_TOKEN, ...) ცარიელებს/ფიქტიურ მნიშვნელობას უსვამს app-ის import-მდე, და/ან secret ველები `SecretStr`/`repr=False`. Tests ლოკალურ `.env`-ზე არ უნდა იყვნენ დამოკიდებული.
  - Verify: ტესტი — `repr(get_settings())` არ შეიცავს secret-ს; `pytest -q` გადის `.env`-ის გარეშეც (ცარიელი env-ით).
  - ⚠️ მფლობელს: ტრანსკრიპტში უკვე გამოჩნდა Gemini key, FB_APP_SECRET, Supabase service-role და FB_TOKEN_ENCRYPTION_KEY — როტაცია საკუთარ შეფასებაზე.
- [x] **T20 — CRITICAL (finish-check): deploy-მდე შექმნილ `new` შეკვეთებზე მარაგი არასწორად დაითვლება** · `supabase/one-off/release_legacy_new_order_stock.sql`
  - ძველი კოდი მარაგს `create_order`-ისას აკლებდა; ახალი `new`-ს „მარაგი არ ჩამოწერილა"-დ თვლის → `new → processing` მარაგს მეორედ აკლებს (ან 409), `new → cancelled` აღარ აბრუნებს (მარაგი იკარგება). Render-ის deploy-ზე ძველი instance რამდენიმე წუთი კიდევ იღებს შეკვეთებს ძველი წესით.
  - Fix: ერთჯერადი SQL (მფლობელი უშვებს backend deploy-ის დასრულებისთანავე): preview → cutoff (ახალი instance-ის live დრო) → `apply_stock_delta(..., +1)` cutoff-მდე შექმნილ `new` შეკვეთებზე, ერთ ტრანზაქციაში, double-run-ისგან დაცვით. Deploy plan-ში ცალკე ნაბიჯი.
  - Verify: SQL-ის ხელით გადამოწმება RPC-სთან; რეალურ Postgres-ზე ვერ გაიშვება (მფლობელი).
- [x] **T21 — IP-ლიმიტი (ip, shop)-ზე, 20/დღე (მფლობელის გადაწყვეტილება 2026-10-08)** · `backend/app/api/orders.py`, `backend/app/core/ratelimit.py`
  - ახლა `create_order_day` 20/დღე მხოლოდ IP-ზეა და ყველა მაღაზიაზე საერთოა (CGNAT-ის რისკი). გადავიდეს key-ზე `(ip, shop_id)`; ლიმიტი 20/დღე რჩება. წუთობრივი `create_order` (10/წთ, IP) უცვლელია.
  - Verify: ტესტი — ერთი IP + shop A: 21-ე → 429; იგივე IP + shop B ჯერ გადის; სხვა IP + shop A გადის; PROJECT.md Decision Log-ის B-1 ჩანაწერი განახლდეს.
- [x] **T22 — should-fix (ლაივ-შემოწმებიდან): INFO ლოგები production-ში არ ჩანს; `peer` გაყალბებადია (uvicorn proxy headers)** · `backend/app/main.py`, `backend/app/core/ratelimit.py`
  - (ა) მიზეზი: `logging.getLogger("app")`-ზე არც handler, არც level არ არის მორგებული (`basicConfig` არსად არის); uvicorn მხოლოდ საკუთარ `uvicorn*` logger-ებს აყენებს → `app`-ის INFO ჩანაწერები იკარგება, WARNING-ები კი lastResort handler-ით ჩანს. ამიტომ `client-ip debug` (INFO) ლოგში არ გამოჩნდა — და ბოტის/webhook-ის სხვა `logger.info` ჩანაწერებიც production-ში უხილავია.
  - (ბ) uvicorn-ის proxy-headers (ნაგულისხმევად ჩართულია; access log-ში `1.2.3.4:0` ამას აჩვენებს) `request.client.host`-ს XFF-ით ანაცვლებს → `peer` კლიენტის კონტროლშია. `_client_ip` პირველ რიგში XFF-ის მარჯვენა ჩანაწერს იღებს (ეს გაყალბებას უძლებს), მაგრამ fallback (`entries < hops`) `peer`-ზეა → გაყალბებადი. სხვა გამოყენება: `admin.py:154` (მხოლოდ დიაგნოსტიკა).
  - Fix: (1) `LOG_LEVEL` (default INFO) — `app` logger-ი stdout-ზე; **წინასწარ გადაამოწმე ყველა `logger.info`/`debug` — PII (ტექსტი, PSID, ტელეფონი, token) არ იწერებოდეს**; (2) production-ში `_client_ip` fallback = ფიქსირებული საერთო bucket (`"unknown"`) და არა `peer`; dev-ში peer; ტესტი — გაყალბებული peer (XFF-ის გარეშე/ცოტა ჩანაწერით) ლიმიტს ვერ აცდენს; (3) მფლობელს ვთავაზობ (კოდი არა): Render start command-ში `--no-proxy-headers`, რომ `request.client` რეალური socket peer იყოს (access log-ში IP-ები ვეღარ გამოჩნდება).
  - Verify: ტესტები; ლოგის ფორმატი/ლოგში secrets არ ხვდება.
- [x] **T23 — Supabase-ის ახალ API key-ებზე გადასვლა (ძველი legacy service_role გაჟონა)** · `backend/app/config.py`, `core/supabase_client.py`, `core/security.py`, `frontend/src/**`, `frontend/public/config.js`
  - მფლობელის გადაწყვეტილება (2026-10-09): backend → `sb_secret_...` (service_role-ის ნაცვლად), frontend → `sb_publishable_...` (anon-ის ნაცვლად); legacy key-ები ბოლოს ითიშება. key-ების მნიშვნელობებს მფლობელი სვამს, აგენტი არ ხედავს.
  - გადაწყვეტილებები: ახალი სახელები `SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_SECRET_KEY`; ძველი `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` მუშაობს fallback-ად (pydantic AliasChoices; ახალი სახელი უპირატესია) — უსაფრთხო rollout და rollback env-ის მეშვეობით. supabase-py 2.32.0 key-ის ფორმატს არ ამოწმებს (მხოლოდ ცარიელს). frontend: `supabase-js ^2.112.3`; `config.js`-ში ველი `SUPABASE_PUBLISHABLE_KEY` (მნიშვნელობა ჯერ უცვლელი, მფლობელი ცვლის).
  - Verify: ტესტები (ახალი და ძველი env სახელი, ახალი უპირატესია, secrets repr-ში არ ჩანს); `npm run build` + `dist/` commit-ში; Deploy plan — ზუსტი ნაბიჯები.
  - ⚠️ ვერ გადამოწმდება offline: sb_secret key-ის მუშაობა supabase-py-ს `Authorization: Bearer <key>` header-ით PostgREST/Storage/Auth-ზე — მხოლოდ ლაივზე (შემოწმების სია Deploy plan-შია).

### Stage 10 — აუდიტის გადამოწმების ისტორია (Stage 11-ის წყარო)
### აუდიტის გადამოწმების შედეგი (27 პუნქტი)
- **(ა) უკვე გასწორებულია:** #7 `/test-chat` fail-open → T3 (`APP_ENV` default `production`); #10 XFF-ის ნდობა → T17 + T22 (მარჯვენა hop, `CLIENT_IP_TRUSTED_HOPS=3`, peer აღარ გამოიყენება); #26 `admin_email` → F-08 (კონფიგში აღარ არსებობს; `ADMIN_USER_IDS`, ცარიელი = fail-closed).
- **(ბ) რეალურია:** #2, #8, #21 → S11-1..3 (should-fix). nit-ები → Backlog: #15, #17, #24, #27, #1-ის ნარჩენი. #23 უკვე Backlog-შია.
- **(გ) არ შეესაბამება / ზედმეტია:** #1, #3, #4, #5, #6, #9, #11, #12, #13, #14, #16, #18, #19, #20, #22, #25 → PROJECT.md `Accepted Risks` (მიზეზებით).
