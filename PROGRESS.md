# Progress

## Current Stage
Stage 10 — Audit fixes

აუდიტი 2026-10-08 (standard-reviewer, ორი ნაწილი: A — isolation/auth/secrets, B — public/webhook/bot/uploads).
ID-ები (A-n / B-n) commit message-ში იწერება: `fix(scope): ... (A-1)`.
შენიშვნა: მიგრაციის ფაილს აგენტი წერს, **გაშვება — მფლობელი, ხელით** (Supabase SQL Editor),
backend-ის deploy-მდე ან მის შემდეგ — task-ში მითითებული რიგით.

## Tasks
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

## Deploy plan
> მფლობელის გადაწყვეტილება (2026-10-08): მიგრაციებს ახლა არ უშვებს — ყველა task-ის შემდეგ ერთი დაგეგმილი deploy.
> სექცია ივსება ყოველი მიგრაციის/frontend ცვლილების დამატებისას; საბოლოო რიგი — Stage-ის ბოლოს.
- **Migrations დაწერილი, გაუშვებელი:** `0017_revoke_shops_delete.sql` (T5) · `0018_orders_privileges.sql` (T6; PRE-CHECK query ფაილის header-ში; მოსალოდნელი verification: t,f,f,f,f,f,t,t,1,t) · `0019_upgrade_requests_checks.sql` (T8; PRE-CHECK 0 მწკრივი; verification: chk_valid=2, insert_policy_ok=t; status CHECK-ში 'cancelled' შედის — shops.py:67 იყენებს) · `0020_instagram_unique.sql` (T9; PRE-CHECK დუბლიკატები → 0 მწკრივი; verification: index_ok=1, duplicates=0; მიგრაციამდე backend deploy სასურველია; connect ახლა უარს იღებს `ig_taken`-ით)
- **წამკითხველი (გაუშვი ჯერ):** `supabase/checks/check_0014_0016.sql` (T15) — ყველა ok=true უნდა იყოს
- **Frontend build:** T18-მა შეცვალა `fbConnect.js` და `dist/` უკვე rebuild-ებულია და commit-შია (finish-check-ზე `npm run build` იგივე შედეგს იძლევა) — დამატებითი build არ სჭირდება.
- **ლოკალური წინაპირობა:** შენს `.env`-ში `APP_ENV=development` (T3: default ახლა production).

### რიგი და შემოწმება
1. **წამკითხველი:** `supabase/checks/check_0014_0016.sql` SQL Editor-ში → ყველა `ok=true`? თუ არა — ჯერ აკლია 0014/0015/0016 (ფაილებში verification-ებით), მერე გაგრძელება.
2. **Backend deploy** (⚠️ `CLIENT_IP_DEBUG=true` Render env-ში **deploy-მდე** დააყენე, რომ არასწორი hops-ის ფანჯარა მინიმალური იყოს) ⚠️ deploy-ის შემდეგ **დაუყოვნებლივ** T17-ის ნაბიჯი (ნაბიჯი 7): სანამ `CLIENT_IP_TRUSTED_HOPS` სწორად არ არის, ყველა კლიენტი შეიძლება ერთ IP-bucket-ში მოხვდეს და საჯარო შეკვეთა (20/დღე) მთელ საიტზე ამოიწუროს. (`agent-system` → `main` merge/push — შენი თანხმობით, Render auto-deploy). რატომ პირველი: მიგრაციები backend-ს არ არღვევს, მაგრამ 0020-მდე connect-ის „სხვა მაღაზიიდან IG id-ის მოხსნა" უკვე უნდა მუშაობდეს.
   შემდეგ შეამოწმე: `GET /status` → `env=production`; Messenger-ში ბოტი პასუხობს; საჯარო შეკვეთა მარაგს **არ** ცვლის; პანელში `new → processing` მარაგს აკლებს, `processing → cancelled` აბრუნებს; Actions-ში CI მწვანეა (ახალი ruff ნაბიჯი).
2a. **T20 — ერთჯერადი მარაგის გასწორება (CRITICAL)** — backend deploy-ის live გახდომისთანავე: `supabase/one-off/release_legacy_new_order_stock.sql` (preview → cutoff = Render deploy event-ის დრო → გაშვება ერთხელ). ამის გარეშე deploy-მდე შექმნილი `new` შეკვეთების დადასტურება მარაგს მეორედ დააკლებს, გაუქმება კი ვერ დააბრუნებს.
   პროცედურა: (1) Render → Events-ში ჩაიწერე ახალი deploy-ის ზუსტი live დრო UTC-ში; (2) SQL Editor-ში STEP 1a/1b — `EDIT_CUTOFF` ჩაანაცვლე ამ დროით, გაუშვი, შეამოწმე `orders_to_process` და `newest < cutoff`, შეინახე 1b შედეგი; (3) STEP 2-ში იგივე cutoff და გაშვება; (4) STEP 3a: `details` → `orders_processed=N` = 1a-ის რიცხვს. ორჯერ გაშვება PK-ით ჩავარდება და მარაგს არ შეცვლის.
   ⚠️ ფანჯარა deploy-სა და სკრიპტს შორის: ამ ხანში გაუქმებული ძველი `new` შეკვეთის მარაგი არ დაბრუნდება, `processing`-ზე გადაყვანილისა კი ორჯერ დაიკლება — დროულად გაუშვი და ფანჯარაში შეცვლილები ხელით გადაამოწმე (`updated_at >= cutoff and created_at < cutoff`). SQL რეალურ Postgres-ზე გაუშვებელია — პირველი გაშვება შენთან.
3. **`0017_revoke_shops_delete.sql`** → verification: `anon_delete=false, auth_delete=false, service_delete=true, auth_select=true` → ხელით: admin-იდან სატესტო მაღაზიის წაშლა, Storage-ში საქაღალდე გაქრა.
4. **`0018_orders_privileges.sql`** → ჯერ PRE-CHECK (0 მწკრივი), მერე გაშვება → verification `t,f,f,f,f,f,t,t,1,t` → პანელში: სტატუსის შეცვლა მუშაობს; `done/cancelled`-ის წაშლა მუშაობს; `new/processing`-ის წაშლა → 409.
5. **`0019_upgrade_requests_checks.sql`** → PRE-CHECK (0 მწკრივი) → verification `chk_valid=2, insert_policy_ok=t` → პანელში პაკეტის მოთხოვნა მუშაობს; მეორე მოთხოვნა პირველს `cancelled`-ზე გადაიყვანს; admin approve/reject მუშაობს.
6. **`0020_instagram_unique.sql`** → PRE-CHECK დუბლიკატებზე (0 მწკრივი; თუ არა — ჯერ გაასუფთავე) → verification `index_ok=1, duplicates=0` → IG-ის connect სხვა მაღაზიიდან უკვე დაკავებულ ანგარიშზე → უარი `ig_taken` შეტყობინებით; იგივე მაღაზიის ხელახალი connect გადის.
7. **T17** (კლიენტის IP Render-იდან): deploy-ის შემდეგ diagnostic დროებით ჩართე → ერთი მოთხოვნა ცნობილი IP-დან (+ გაყალბებული `X-Forwarded-For`) → Render-ის ლოგში ნახე რეალური XFF → დააყენე `CLIENT_IP_TRUSTED_HOPS` → გამორთე diagnostic. (T13/ORIGIN_SECRET — Backlog.)
8. **საგანგებო ნაბიჯი (2026-10-16):** თუ `gemini-2.5-flash` გაითიშა (ბოტი 404/ცარიელ პასუხებს აბრუნებს), Render-ზე `GEMINI_MODEL=gemini-3.5-flash` და restart. ⚠️ 3.5-ზე thinking-ის გამო პასუხები იჭრება `max_output_tokens=800`-ზე (ტესტზე 4/10 ჩამოიჭრა) — ეს პირდაპირ ბოტს აფუჭებს; ამიტომ ეს მხოლოდ ბოლო გამოსავალია, სანამ `thinking_config` კოდში არ შეიზღუდება (Backlog T12).
9. **key-ების როტაცია** (Gemini, `FB_APP_SECRET`, Supabase service-role): ტრანსკრიპტში გამოჩნდა — **როდის გააკეთებ, შენ წყვეტ**. `FB_TOKEN_ENCRYPTION_KEY`-ს **არ ვეხებით** (შეცვლა დაშიფრულ page token-ებს გამოუსადეგარს გახდის). როტაციისას: ახალი მნიშვნელობა Render-ზე + ლოკალურ `.env`-ში; `FB_APP_SECRET` — Meta App Dashboard-ში reset-იც, შემდეგ webhook-ის ხელმოწერა/OAuth შეამოწმე (ბოტი პასუხობს, connect მუშაობს); service-role — Supabase Settings → API.

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
### Finish-check nits (2026-10-08, standard-reviewer)
- 0018-ის header-ის დასაბუთება ზუსტი არ არის: გამყიდველს PostgREST-ით `status`-ის პირდაპირ შეცვლა მაინც შეუძლია (`new → processing` დაკლების გარეშე, მერე API-ით `→ cancelled` = მარაგი +N). ზიანი მხოლოდ საკუთარ მარაგზე (`products.quantity`-საც ისედაც ცვლის, 0015). სრულად დახურვა: UPDATE-ის სრული revoke და status-ის ჩაწერა service-ით ownership-ის შემდეგ.
- `orders.py:410-411`: `_apply_stock_delta(+1)` შეცდომა სტატუსის შეცვლის შემდეგ 500-ს აბრუნებს — try/except + `logger.exception`.
- `facebook.py`: პარალელური connect-ის race-ზე unique violation `page_taken`-ად მიდის `ig_taken`-ის ნაცვლად; `any(...)` `.neq`-ის შემდეგ ზედმეტია.
- `admin.py:396-401`: storage cleanup-ის ციკლი — `break`, თუ `paths` არ შეცვლილა.
- `webhook.py`: `_RATE_PER_SHOP = 30/წთ` ყველა პაკეტისთვის ერთია; 5 spam PSID მაღაზიის ბოტს წუთით აჩერებს.
- README: 157 („19 მიგრაცია" → 20), 175/201 („მარაგი ავტომატურად კლებულობს" → `processing`-ზე).
### Nits (აუდიტიდან)
- **A-9 / B-6** — საიდუმლოები fail-open: ცარიელი `FB_APP_SECRET`-ით HMAC ყალბდება; `"chatassist"` fallback deletion კოდზე;
  production-ში `FB_TOKEN_ENCRYPTION_KEY`/`FB_APP_SECRET` startup-ზე არ მოწმდება; `encrypt` `subscribe_page`-ის შემდეგაა (`api/facebook.py:253`).
- **A-6** — `knowledge` PostgREST-ით პირდაპირ ჩაწერადია → free პაკეტი PDF-ცოდნის gate-ს უვლის (`0015_column_privileges.sql:43`).
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
- Finish-check this stage: done
- Fix rounds this stage: 1/2
- Failed attempts: —

## Last Session
- Date: 2026-10-08
- Done: კოდის/დოკუმენტების შესწავლა; PROJECT.md (Appendix A); CLAUDE.md ბრძანებებით;
  აუდიტი (standard-reviewer ×2); PROGRESS.md; verify.sh — agent-dashboard-ის 3 ცვლილება (CHECKS ცარიელი).
- Verification: `pytest -q` → 114 passed (offline, ყველა secret env ცარიელი); verify.sh — `bash -n` + scratchpad-ში
  pass/fail/empty სიმულაცია (exit 0/2/0, Verify event სწორად იწერება). აუდიტის მთავარი მტკიცებები ხელით გადამოწმდა კოდში.
- Known issues / blockers: Cloudflare არ გამოიყენება (T17 ცვლის IP-ის წყაროს); მიგრაციების (T5 = 0017 დაწერილია, გაუშვებელი; T6, T8, T9) გაშვება — მფლობელი.
- Next: Stage Done (დარჩენილი მხოლოდ მფლობელის ნაბიჯები — Deploy plan)
