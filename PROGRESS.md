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
- [ ] **T2 — B-1 (critical): ყალბი საჯარო შეკვეთებით მარაგის განულება** · `backend/app/api/orders.py:203-364`
  - ✅ გადაწყვეტილება (მფლობელი, 2026-10-08): ვარიანტი (გ) — მარაგი იკლებს **მხოლოდ `new → processing` გადასვლისას**;
    დამატებით **IP-ზე დღიური ლიმიტი** საჯარო შეკვეთებზე.
  - შედეგები, რაც ამ ცვლილებას თან მოჰყვება (გასათვალისწინებელი):
    - `create_order` აღარ იძახებს `decrement_stock`-ს; `new` შეკვეთის გაუქმებისას მარაგი **არ ბრუნდება** (არაფერი ჩამოვრიცხულა).
    - `new → processing`: ატომური დაკლება; თუ მარაგი არ ჰყოფნის → 409 + გასაგები შეტყობინება გამყიდველს.
    - `processing/done → cancelled` აბრუნებს მარაგს (როგორც ახლა); F-06 reopen-ის ლოგიკა ახალ მდგომარეობებს მოერგოს.
    - `public-menu` / ბოტი აჩვენებს რეალურ მარაგს, `new` შეკვეთები მარაგს აღარ ამცირებს → შეიძლება overselling `new`-ში (მისაღებია, გამყიდველი ადასტურებს).
    - IP-ლიმიტი in-memory-ია (deploy-ზე ნულდება) და **მხოლოდ მაშინ არის სანდო, როცა `ORIGIN_SECRET` აქტიურია (იხ. T13)**.
  - Verify: ტესტები — შეკვეთა მარაგს არ ცვლის; processing-ზე იკლებს; არასაკმარისი მარაგი → 409; cancel processing-იდან აბრუნებს;
    IP-ის დღიური ლიმიტი → 429.
- [ ] **T3 — A-4 (hardening, დაბალი): `APP_ENV` default fail-open** · `backend/app/config.py:19`
  - მფლობელმა დაადასტურა: Render-ზე `APP_ENV=production` (`/status` → `env=production`), ე.ი. ლაივ-რისკი ახლა არ არსებობს.
    Fix მაინც ღირს (მომავალი გარემო/აღდგენა): default `production`; dev-ში `.env`-ით `APP_ENV=development`; tests/conftest ცხადად `development`.
  - Verify: ტესტი — env-ის გარეშე `is_production is True`; არსებული ტესტები გადის.
- [ ] **T4 — B-2 (should-fix, high): xlsx-ის სვეტებით OOM** · `backend/app/services/import_products.py:62`
  - `iter_rows` `max_col`-ის გარეშე: 4.8KB ფაილი `dimension=A1:XFD…`-ით ≈ 660MB (გაზომილი ლოკალურად) → instance OOM.
  - Fix: `iter_rows(max_col=MAX_COLS)`; `load_workbook`-მდე zip-ის გაშლილი ზომის ჭერი.
  - Verify: ტესტი სინთეზური xlsx-ით (ფართო dimension) — სწრაფად ბრუნდება / ValueError.
- [ ] **T5 — A-1 (should-fix): მაღაზიის პირდაპირი DELETE PostgREST-ით → storage კვოტის და კლიენტების მრიცხველის გვერდის ავლა** ·
  `supabase/migrations/0001_init.sql:104-107`, `backend/app/api/admin.py:381-383`
  - Fix: მიგრაცია `0017` — `revoke delete on public.shops from anon, authenticated`; `admin.delete_shop` შლის `product-images/{shop_id}/*`-საც.
  - Verify: ტესტი — admin delete იძახებს storage remove-ს; მიგრაციის verification query.
- [ ] **T6 — A-2 (should-fix): `orders`-ზე column privileges / status CHECK არ არის** · `supabase/migrations/0002_orders.sql`
  - გამყიდველს PostgREST-ით შეუძლია `items`/`total` შეცვლა და მერე API-ით გაუქმება → მარაგის გაბერვა; აქტიური შეკვეთის წაშლა (F-07-ის გვერდის ავლა).
  - Fix: მიგრაცია — `revoke update, delete` + `grant update (status)`; `check (status in (...))`; delete policy მხოლოდ `done`/`cancelled`.
  - Verify: SQL verification query მიგრაციაში; API ტესტები გადის.
- [ ] **T7 — B-3 (should-fix): webhook-ზე წუთობრივი ლიმიტი არ არის — ერთი კლიენტი ამოწურავს საერთო Gemini კვოტას / threadpool-ს** ·
  `backend/app/api/webhook.py:262-273`
  - Fix: in-memory ლიმიტი `(shop_id, psid)` (~6/წთ) და `shop_id` (~30/წთ); გადაჭარბება — ჩუმად გამოტოვება + log.
  - Verify: ტესტი — N+1-ე შეტყობინება `get_bot_reply`-ს არ იძახებს.
- [ ] **T8 — A-3 (should-fix): `upgrade_requests` insert policy სვეტებს არ ზღუდავს** · `supabase/migrations/0005_upgrade_requests.sql:22-27`
  - Fix: მიგრაცია — WITH CHECK `status='pending' and resolved_at is null and requested_tier in (...)` + CHECK constraints.
  - Verify: SQL verification query.
- [ ] **T9 — A-5 / B-9 (should-fix, low): `instagram_account_id` არ არის unique → IG DM შეიძლება სხვა tenant-ის მაღაზიას მიება** ·
  `supabase/migrations/0006_instagram.sql:11`, `backend/app/api/facebook.py:251-262`, `backend/app/api/webhook.py:209-213`
  - Fix: connect-ზე იგივე IG id სხვა მაღაზიიდან null-დება; მიგრაცია — partial unique index (`where instagram_account_id is not null`).
    ⚠️ მიგრაციამდე live DB-ში დუბლიკატები შესამოწმებელია (მფლობელი).
  - Verify: ტესტი connect-ზე; SQL verification query.
- [ ] **T10 — B-4 (should-fix, low): საჯარო შეკვეთა იღებს `is_active=false` პროდუქტს** · `backend/app/api/orders.py:255-262`
  - Fix: `.eq("is_active", True)` `db_products` select-ში.
  - Verify: ტესტი — არააქტიური პროდუქტი → „ვერ მოიძებნა", მარაგი უცვლელი.
- [ ] **T11 — B-5 (should-fix): webhook-ის ხელმოწერას ტესტი არ აქვს** · `backend/tests/`
  - Fix: ტესტები — სწორი ხელმოწერა → 200; არასწორი/არარსებული → 403. (ცარიელი secret → 403 ტესტი — მხოლოდ Backlog-ის A-9/B-6-ის გასწორების შემდეგ.)
  - Verify: `pytest -q`.
- [ ] **T12 — Gemini: გადასვლა `gemini-3.5-flash`-ზე (2.5 Flash ითიშება 2026-10-16)** · `GEMINI_MODEL`
  - ეტაპი 1: ლოკალური შედარების სკრიპტი (მარტივი, ერთჯერადი, scratchpad-ში) — იგივე ქართული შეკითხვები ორივე მოდელზე, პასუხები გვერდიგვერდ.
    ⚠️ საჭიროებს რეალურ Gemini key-ს — **გაშვებამდე მფლობელს ვეკითხები** (key-ს მფლობელი აძლევს; `.env` არ იკითხება).
  - ეტაპი 2: შედარების შედეგის დამტკიცების შემდეგ — Render-ზე `GEMINI_MODEL=gemini-3.5-flash` (მფლობელი ცვლის თვითონ) + კოდის default-ის განახლება.
  - შესამოწმებელი: ფასი/ტოკენი ([project-costs-pricing] memory), `max_output_tokens`, multimodal (ფოტოს გაგება), `[[HANDOFF]]` ნიშნის დაცვა.
  - Deadline: **2026-10-16**.
- [ ] **T13 — ORIGIN_SECRET Render-ზე (მფლობელის ქმედება, კოდი არ სჭირდება)** · `backend/app/main.py:124-168`
  - წინაპირობა: Cloudflare ნამდვილად პროქსირებს `chatassist.ge`-ს (ნარინჯისფერი ღრუბელი). ინსტრუქცია — იხ. ჩატის ახსნა; ჩემგან Render-ზე არაფერი კეთდება.
  - Verify (მფლობელი): `curl -i https://<render-url>.onrender.com/status` → 403; `https://chatassist.ge/status` → 200; Messenger-ში ბოტი პასუხობს.

## Backlog (needs user decision)
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
- Finish-check this stage: not run
- Fix rounds this stage: 0/2
- Failed attempts: —

## Last Session
- Date: 2026-10-08
- Done: კოდის/დოკუმენტების შესწავლა; PROJECT.md (Appendix A); CLAUDE.md ბრძანებებით;
  აუდიტი (standard-reviewer ×2); PROGRESS.md; verify.sh — agent-dashboard-ის 3 ცვლილება (CHECKS ცარიელი).
- Verification: `pytest -q` → 114 passed (offline, ყველა secret env ცარიელი); verify.sh — `bash -n` + scratchpad-ში
  pass/fail/empty სიმულაცია (exit 0/2/0, Verify event სწორად იწერება). აუდიტის მთავარი მტკიცებები ხელით გადამოწმდა კოდში.
- Known issues / blockers: Cloudflare-ის პროქსირება ჯერ დაუდასტურებელია (T13/T2 დამოკიდებულია); მიგრაციების (T5, T6, T8, T9) გაშვება — მფლობელი.
- Next: T2 (critical, პირველი) → T3 → T4 → T10 → T11 → მიგრაციები T5/T6/T8/T9. T12/T13 — მფლობელთან.
